"""NOMOS pdp.decisor — o Policy Decision Point (ABSORPTION-01 / FASE 2).

O PDP é a barreira: nada de efeito externo sem uma decisão ALLOW dele. Ele não
executa nada e não conhece adapters — só decide, de forma determinística e
auditável.

Cadeia que ele fecha:

    pedido → normalização → identidade/contexto → capacidade → risco
           → PDP.decidir → decisão

Regra de ouro: **default deny**. Toda saída que não seja explicitamente ALLOW
é DENY, e qualquer erro inesperado vira DENY (nunca exceção que o chamador
possa interpretar como "seguiu em frente").

A classificação de risco NÃO é inventada aqui: vem do registro de capacidades
(que por sua vez a tira de `agents.manifest.FERRAMENTAS` / `kernel.policy`).
O PDP nunca rebaixa risco; só recusa.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from nomos.pdp.autorizacao import (
    Autorizacao, Chaveiro, ErroArmazem, _ordem_risco, agora_utc, hash_contrato,
)


def _no_escopo(recurso: str, caminhos) -> bool:
    """Contenção por COMPONENTE, sobre o caminho CANONICALIZADO.

    A primeira versão comparava por prefixo de string (`startswith`). Um censo
    adversarial mostrou o furo: `/ws/../etc/passwd` "começa com" `/ws` e
    passava — resolvendo, na verdade, para `/etc/passwd`. Para as capacidades
    de adapter o `resolver()` pegaria depois (defesa em profundidade), mas as
    ferramentas NATIVAS (`arquivo_ler`, `arquivo_resumir`) não têm resolver
    nenhum: ali o escopo do PDP era o único confinamento, e um `..` o
    derrotava.
    """
    import os
    if not caminhos:
        return True
    try:
        real = os.path.realpath(os.path.abspath(recurso))
    except Exception:
        return False
    for bruto in caminhos:
        try:
            raiz = os.path.realpath(os.path.abspath(bruto))
        except Exception:
            continue
        if real == raiz:
            return True
        try:
            if os.path.commonpath([real, raiz]) == raiz:
                return True
        except ValueError:
            continue
    return False


class Efeito(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"


class Motivo(str, Enum):
    OK = "ok"
    PEDIDO_MALFORMADO = "pedido_malformado"
    CONTEXTO_INCOMPLETO = "contexto_incompleto"
    SEM_AUTORIZACAO = "sem_autorizacao"
    AUTORIZACAO_MALFORMADA = "autorizacao_malformada"
    ASSINATURA_INVALIDA = "assinatura_invalida"
    CHAVE_DESCONHECIDA = "chave_desconhecida"
    EXPIRADA = "expirada"
    AINDA_NAO_VALIDA = "ainda_nao_valida"
    AUDIENCIA_ERRADA = "audiencia_errada"
    SUJEITO_ERRADO = "sujeito_errado"
    CAPACIDADE_DESCONHECIDA = "capacidade_desconhecida"
    CAPACIDADE_NAO_CONCEDIDA = "capacidade_nao_concedida"
    RECURSO_FORA_DO_ESCOPO = "recurso_fora_do_escopo"
    ARGUMENTO_FORA_DO_ESCOPO = "argumento_fora_do_escopo"
    RISCO_ACIMA_DO_AUTORIZADO = "risco_acima_do_autorizado"
    NONCE_AUSENTE = "nonce_ausente"
    NONCE_REPETIDO = "nonce_repetido"
    ATENUACAO_INVALIDA = "atenuacao_invalida"
    POLITICA_INDISPONIVEL = "politica_indisponivel"
    ARMAZEM_INDISPONIVEL = "armazem_indisponivel"
    REGISTRO_INDISPONIVEL = "registro_indisponivel"
    CAPACIDADE_MUDOU = "capacidade_mudou"
    ERRO_INTERNO = "erro_interno"


@dataclass(frozen=True)
class Pedido:
    """O que se quer fazer. `argumentos` é dado, nunca autoridade."""
    capacidade: str
    sujeito: str
    recurso: str = ""
    argumentos: dict = field(default_factory=dict)
    nonce: str = ""


@dataclass(frozen=True)
class Decisao:
    efeito: Efeito
    motivo: Motivo
    detalhe: str = ""
    capacidade: str = ""
    risco: str = ""
    hash_autorizacao: str = "-"

    @property
    def permitido(self) -> bool:
        # Uma única definição de "pode": qualquer outra coisa é DENY.
        return self.efeito is Efeito.ALLOW


class Decisor:
    """PDP. Sem estado de negócio; só chaveiro, armazém de nonce e relógio."""

    def __init__(self, chaveiro: Chaveiro, registro, *, audiencia: str,
                 armazem_nonce=None, exigir_nonce: bool = True,
                 tolerancia_relogio_s: int = 60,
                 agora_fn=agora_utc, audit=None):
        self.chaveiro = chaveiro
        self.registro = registro
        self.audiencia = audiencia
        self.armazem = armazem_nonce
        self.exigir_nonce = exigir_nonce
        self.tolerancia = timedelta(seconds=tolerancia_relogio_s)
        self._agora = agora_fn
        self.audit = audit

    # ------------------------------------------------------------------ API

    def decidir(self, pedido, autorizacao) -> Decisao:
        """Ponto único de decisão. NUNCA levanta: erro inesperado ⇒ DENY."""
        try:
            decisao = self._decidir(pedido, autorizacao)
        except ErroArmazem as exc:
            decisao = self._negar(Motivo.ARMAZEM_INDISPONIVEL, str(exc))
        except Exception as exc:                       # fail-closed total
            decisao = self._negar(Motivo.ERRO_INTERNO, type(exc).__name__)
        self._auditar(pedido, decisao)
        return decisao

    # -------------------------------------------------------------- interno

    def _negar(self, motivo: Motivo, detalhe: str = "", capacidade: str = "",
               risco: str = "", hash_auth: str = "-") -> Decisao:
        return Decisao(Efeito.DENY, motivo, detalhe, capacidade, risco, hash_auth)

    def _decidir(self, pedido, autorizacao) -> Decisao:
        # 0. forma do pedido
        if not isinstance(pedido, Pedido):
            return self._negar(Motivo.PEDIDO_MALFORMADO, "pedido não é Pedido")
        if not isinstance(pedido.capacidade, str) or not pedido.capacidade:
            return self._negar(Motivo.PEDIDO_MALFORMADO, "capacidade vazia")
        if not isinstance(pedido.argumentos, dict):
            return self._negar(Motivo.PEDIDO_MALFORMADO, "argumentos não são dict")
        if not isinstance(pedido.sujeito, str) or not pedido.sujeito:
            return self._negar(Motivo.CONTEXTO_INCOMPLETO, "sujeito ausente")

        # 1. autorização presente e íntegra
        if autorizacao is None:
            return self._negar(Motivo.SEM_AUTORIZACAO, "nenhuma autorização apresentada",
                               capacidade=pedido.capacidade)
        if not isinstance(autorizacao, Autorizacao):
            return self._negar(Motivo.AUTORIZACAO_MALFORMADA, "tipo inesperado",
                               capacidade=pedido.capacidade)
        chash = hash_contrato(autorizacao)
        if not autorizacao.id_chave:
            return self._negar(Motivo.CHAVE_DESCONHECIDA, "sem id_chave",
                               capacidade=pedido.capacidade, hash_auth=chash)
        if self.chaveiro.obter(autorizacao.id_chave) is None:
            return self._negar(Motivo.CHAVE_DESCONHECIDA,
                               f"id_chave {autorizacao.id_chave!r}",
                               capacidade=pedido.capacidade, hash_auth=chash)
        if not self.chaveiro.verificar(autorizacao):
            return self._negar(Motivo.ASSINATURA_INVALIDA, "HMAC não confere",
                               capacidade=pedido.capacidade, hash_auth=chash)

        # 2. tempo (com tolerância de relógio)
        agora = self._agora()
        if not isinstance(autorizacao.expira_em, datetime) or \
           not isinstance(autorizacao.emitida_em, datetime):
            return self._negar(Motivo.AUTORIZACAO_MALFORMADA, "datas inválidas",
                               capacidade=pedido.capacidade, hash_auth=chash)
        if agora > autorizacao.expira_em + self.tolerancia:
            return self._negar(Motivo.EXPIRADA, f"expirou em {autorizacao.expira_em}",
                               capacidade=pedido.capacidade, hash_auth=chash)
        if agora + self.tolerancia < autorizacao.emitida_em:
            return self._negar(Motivo.AINDA_NAO_VALIDA, "emitida no futuro",
                               capacidade=pedido.capacidade, hash_auth=chash)

        # 3. audiência e sujeito — token de um PEP não vale noutro
        if autorizacao.audiencia != self.audiencia:
            return self._negar(Motivo.AUDIENCIA_ERRADA,
                               f"para {autorizacao.audiencia!r}, aqui é {self.audiencia!r}",
                               capacidade=pedido.capacidade, hash_auth=chash)
        if autorizacao.sujeito != pedido.sujeito:
            return self._negar(Motivo.SUJEITO_ERRADO,
                               f"autorização de {autorizacao.sujeito!r}",
                               capacidade=pedido.capacidade, hash_auth=chash)

        # 4. capacidade existe no registro (fonte da verdade sobre risco)
        if self.registro is None:
            return self._negar(Motivo.REGISTRO_INDISPONIVEL, "sem registro",
                               capacidade=pedido.capacidade, hash_auth=chash)
        try:
            conhecida = self.registro.conhecida(pedido.capacidade)
            categoria = self.registro.categoria_de(pedido.capacidade)
            risco = self.registro.risco_de(pedido.capacidade)
        except Exception as exc:
            return self._negar(Motivo.POLITICA_INDISPONIVEL, type(exc).__name__,
                               capacidade=pedido.capacidade, hash_auth=chash)
        if not conhecida or categoria is None:
            return self._negar(Motivo.CAPACIDADE_DESCONHECIDA, pedido.capacidade,
                               capacidade=pedido.capacidade, hash_auth=chash)

        # 4b. REGISTRY RACE (ABSORPTION-03/FASE 4): o descritor da capacidade
        # mudou entre a emissão e agora? Uma autorização vale para o mundo que
        # ela viu — risco/idempotência/executor alterados invalidam a decisão
        # que foi tomada com os valores antigos.
        esperada = dict(autorizacao.versoes).get(pedido.capacidade)
        if esperada:
            from nomos.adapters.contrato import versao_de_capacidade
            try:
                atual_v = versao_de_capacidade(self.registro, pedido.capacidade)
            except Exception as exc:
                return self._negar(Motivo.POLITICA_INDISPONIVEL, type(exc).__name__,
                                   capacidade=pedido.capacidade, hash_auth=chash)
            if atual_v != esperada:
                return self._negar(
                    Motivo.CAPACIDADE_MUDOU,
                    f"descritor mudou desde a emissão ({esperada}→{atual_v or 'removida'})",
                    capacidade=pedido.capacidade, risco=risco, hash_auth=chash)

        # 5. a capacidade pedida foi de fato concedida?
        if pedido.capacidade not in autorizacao.capacidades:
            return self._negar(Motivo.CAPACIDADE_NAO_CONCEDIDA,
                               f"concedidas: {', '.join(sorted(autorizacao.capacidades))}",
                               capacidade=pedido.capacidade, risco=risco, hash_auth=chash)

        # 6. risco do pedido não pode passar do teto autorizado
        if _ordem_risco(risco) > _ordem_risco(autorizacao.risco_max):
            return self._negar(Motivo.RISCO_ACIMA_DO_AUTORIZADO,
                               f"{risco} > {autorizacao.risco_max}",
                               capacidade=pedido.capacidade, risco=risco, hash_auth=chash)

        # 7. recurso dentro do escopo QUE VALE PARA ESTA CAPACIDADE.
        # Capacidade de dados vê o escopo de dados; capacidade de controle vê
        # o de controle. Nenhuma vê os dois, e nenhuma vê o da outra — era
        # essa união que fazia `--scheduler` conceder leitura de `keys/`,
        # `consent.json` e `policy.json` em A0, sem aprovação.
        from nomos.pdp.autorizacao import escopo_de
        escopo = escopo_de(pedido.capacidade, autorizacao)
        if escopo:
            recurso = pedido.recurso or ""
            if not recurso:
                return self._negar(Motivo.RECURSO_FORA_DO_ESCOPO, "recurso vazio",
                                   capacidade=pedido.capacidade, risco=risco,
                                   hash_auth=chash)
            if not _no_escopo(recurso, escopo):
                return self._negar(Motivo.RECURSO_FORA_DO_ESCOPO, recurso,
                                   capacidade=pedido.capacidade, risco=risco,
                                   hash_auth=chash)

        # 8. argumentos não podem contrabandear outro recurso
        fora = self._argumento_fora_do_escopo(pedido, autorizacao)
        if fora:
            return self._negar(Motivo.ARGUMENTO_FORA_DO_ESCOPO, fora,
                               capacidade=pedido.capacidade, risco=risco,
                               hash_auth=chash)

        # 9. anti-replay (uso único)
        if self.exigir_nonce:
            nonce = pedido.nonce or autorizacao.nonce
            if not nonce:
                return self._negar(Motivo.NONCE_AUSENTE, "uso único exigido",
                                   capacidade=pedido.capacidade, risco=risco,
                                   hash_auth=chash)
            if self.armazem is None:
                return self._negar(Motivo.ARMAZEM_INDISPONIVEL, "sem armazém de nonce",
                                   capacidade=pedido.capacidade, risco=risco,
                                   hash_auth=chash)
            if not self.armazem.consumir(nonce, agora):
                return self._negar(Motivo.NONCE_REPETIDO, "nonce já consumido",
                                   capacidade=pedido.capacidade, risco=risco,
                                   hash_auth=chash)

        return Decisao(Efeito.ALLOW, Motivo.OK, "", pedido.capacidade, risco, chash)

    def _argumento_fora_do_escopo(self, pedido, autorizacao) -> str:
        """`alvo` nos argumentos precisa respeitar o MESMO escopo do recurso.

        Sem isto, um pedido com `recurso` dentro do escopo poderia carregar
        `argumentos={"alvo": "/outro/lugar"}` e o adapter agiria fora do que
        foi autorizado — escopo que só vale no papel não é escopo.
        """
        from nomos.pdp.autorizacao import escopo_de

        # `alvo_job` é o alvo de DADOS que uma capacidade de CONTROLE agenda:
        # o job vai agir ali em T2. Ele é conferido contra o escopo de DADOS
        # mesmo quando a capacidade que o carrega é de controle — separar as
        # autoridades não pode significar que agendar escapa do escopo.
        if autorizacao.caminhos:
            # NH-018c: `monitorar_alvo` entra na mesma conferência — um alvo
            # de DADOS novo ganha o verificador existente, não um espelho
            for chave_dado in ("alvo_job", "monitorar_alvo"):
                valor_dado = pedido.argumentos.get(chave_dado)
                if isinstance(valor_dado, str) and valor_dado:
                    if not _no_escopo(valor_dado, autorizacao.caminhos):
                        return f"{chave_dado} {valor_dado}"

        escopo = escopo_de(pedido.capacidade, autorizacao)
        if not escopo:
            return ""
        for chave in ("alvo", "caminho", "destino"):
            valor = pedido.argumentos.get(chave)
            if not valor:
                continue
            if not isinstance(valor, str):
                return f"{chave} não é texto"
            if not _no_escopo(valor, escopo):
                return f"{chave}={valor}"
        return ""

    def _auditar(self, pedido, decisao: Decisao) -> None:
        if self.audit is None:
            return
        cap = getattr(pedido, "capacidade", "?")
        self.audit.append("pdp.decisao", capacidade=str(cap)[:64],
                          efeito=decisao.efeito.value, motivo=decisao.motivo.value,
                          risco=decisao.risco, autorizacao=decisao.hash_autorizacao[:16])
