"""NOMOS kernel.concessoes — consentimento DURÁVEL para registrar capacidade.

O problema que este módulo fecha
--------------------------------
`RegistroCapacidades` vive em memória por processo (ver `orquestracao/registro.py`),
e `AgendadorGovernado._runtime()` constrói um `RuntimeGovernado` NOVO por ocorrência
de job — de propósito, para que política e escopo valham no instante da EXECUÇÃO.
A consequência não intencional: registrar as capacidades de filesystem custa uma
aprovação A5 humana POR CAPACIDADE e POR CONSTRUÇÃO. Medido nesta máquina: 9
aprovações por subida do serviço. Com `KeepAlive`, o pedido expira em 300 s, o
serviço reinicia e a série recomeça — o serviço nunca chega a operar.

A resposta NÃO é enfraquecer o gate. É dar ao dono uma forma de dizer "eu já
autorizei ISTO, e continua valendo" — durável, com prazo, revogável e amarrada à
operação exata que ele leu.

O que uma concessão é (e o que não é)
--------------------------------------
- Vale só para o ato de REGISTRAR (fiação de nome→executor). A EXECUÇÃO continua
  passando pelo PDP/PEP e pelo `RegistroAprovacoes` de uso único — nada aqui
  alcança efeito no mundo.
- É chaveada pelo DIGEST de uma `OperacaoAprovavel`, não pelo nome. O digest cobre
  capacidade, recurso, classe de risco, origem e `versao_da_politica`. Portanto:
  editar `policy.json` invalida TODAS as concessões automaticamente; e uma
  capacidade homônima vinda de outra origem ou classificada com outro risco NÃO é
  coberta pela concessão existente.
- Nunca converte DENY em permissão. Substitui apenas o passo humano de um
  `REQUIRE_APPROVAL` — quem decide isso é `registro.registrar()`, não este módulo.
- Só cobre alvos `registro:` (ver `PREFIXO_ALVO`). Uma concessão jamais pode
  pré-autorizar execução, instalação de skill arbitrária ou qualquer outra
  categoria: `conceder()` recusa fail-closed.
- TTL é OBRIGATÓRIO. Não existe concessão perpétua por omissão.

TTL do PEDIDO ≠ TTL da CONCESSÃO
---------------------------------
`ApprovalQueue` tem TTL de 300 s: é a janela para o humano DECIDIR um pedido, e é
single-use. A concessão nasce DEPOIS de uma decisão humana e tem o próprio prazo,
em dias. Confundir os dois foi a causa raiz do serviço preso em laço.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from nomos.kernel.plataforma import chmod_privado

PREFIXO_ALVO = "registro:"
TTL_PADRAO_DIAS = 30


class ConcessaoError(Exception):
    """Concessão inválida ou fora de escopo — sempre fail-closed."""


class RegistroConcessoes:
    """Concessões duráveis, persistidas em JSON 0600.

    Molde deliberadamente igual ao de `kernel/consent.py`: escrita atômica
    (tmp+replace), arquivo corrompido ⇒ NADA concedido, expiração persiste o
    estado revogado, `panic()` revoga tudo.
    """

    def __init__(self, path: Path, audit=None, clock=time.time):
        self.path = Path(path)
        self.audit = audit
        self.clock = clock

    # ------------------------------------------------------------- estado
    def _ler(self) -> dict:
        # Corrompido/truncado/estrutura errada ⇒ nada concedido. Um registro
        # ilegível NÃO pode virar autorização.
        try:
            dados = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        if not isinstance(dados, dict):
            return {}
        concessoes = dados.get("concessoes")
        return concessoes if isinstance(concessoes, dict) else {}

    def _escrever(self, concessoes: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"versao": 1, "concessoes": concessoes},
                                  indent=2, ensure_ascii=False),
                       encoding="utf-8")
        chmod_privado(tmp, 0o600)
        tmp.replace(self.path)
        chmod_privado(self.path, 0o600)

    def _auditar(self, evento: str, **campos) -> None:
        if self.audit is None:
            return
        try:
            self.audit.append(evento, **campos)
        except Exception:  # noqa: S110 — silêncio DELIBERADO:
            # Auditoria indisponível não pode transformar uma revogação em
            # concessão. Quem CONCEDE trata o erro (ver conceder()).
            pass

    # ---------------------------------------------------------------- API
    def conceder(self, operacao, *, ttl_dias: float = TTL_PADRAO_DIAS,
                 motivo: str = "", dono: str = "") -> dict:
        """Grava a concessão de UMA operação de registro já autorizada.

        Não faz gate: quem chama é responsável por ter obtido a decisão humana
        (a CLI o faz). Aqui só se garante escopo, prazo e trilha.
        """
        recurso = getattr(operacao, "recurso", "") or ""
        if not recurso.startswith(PREFIXO_ALVO):
            raise ConcessaoError(
                f"fora de escopo: concessão só cobre alvos '{PREFIXO_ALVO}*', "
                f"recebido {recurso!r}")
        if ttl_dias <= 0:
            raise ConcessaoError("TTL deve ser positivo — não há concessão perpétua")

        digest = operacao.digest()
        agora = self.clock()
        entrada = {
            "digest": digest,
            "capacidade": getattr(operacao, "capacidade", ""),
            "recurso": recurso,
            "classe_de_risco": getattr(operacao, "classe_de_risco", ""),
            "versao_da_politica": getattr(operacao, "versao_da_politica", ""),
            "concedida_em": round(agora, 3),
            "expira_em": round(agora + ttl_dias * 86400, 3),
            "motivo": str(motivo),
            "dono": str(dono),
        }
        concessoes = self._ler()
        concessoes[digest] = entrada
        self._escrever(concessoes)
        self._auditar("registro.concessao.concedida", digest=digest[:16],
                      capacidade=entrada["capacidade"], recurso=recurso,
                      expira_em=entrada["expira_em"], motivo=str(motivo))
        return dict(entrada)

    def vigente(self, digest: str) -> bool:
        """Existe concessão viva para este digest? Expirada persiste revogada."""
        if not isinstance(digest, str) or not digest:
            return False
        concessoes = self._ler()
        entrada = concessoes.get(digest)
        if not isinstance(entrada, dict):
            return False
        expira = entrada.get("expira_em")
        if not isinstance(expira, (int, float)):
            return False                      # sem prazo legível ⇒ não vale
        if self.clock() >= expira:
            del concessoes[digest]
            self._escrever(concessoes)
            self._auditar("registro.concessao.expirada", digest=digest[:16],
                          capacidade=entrada.get("capacidade", ""))
            return False
        return True

    def revogar(self, digest: str) -> bool:
        concessoes = self._ler()
        entrada = concessoes.pop(digest, None)
        if entrada is None:
            return False
        # Revogar REDUZ autoridade: acontece mesmo que a trilha falhe.
        self._escrever(concessoes)
        self._auditar("registro.concessao.revogada", digest=digest[:16],
                      capacidade=entrada.get("capacidade", ""))
        return True

    def panic(self) -> int:
        """Revogação imediata de todas as concessões."""
        quantas = len(self._ler())
        self._escrever({})
        self._auditar("registro.concessao.panic", quantas=quantas)
        return quantas

    def listar(self) -> list[dict]:
        """Concessões vivas, mais recentes primeiro. Expiradas são varridas."""
        vivas = []
        for digest in list(self._ler()):
            if self.vigente(digest):
                vivas.append(dict(self._ler()[digest]))
        return sorted(vivas, key=lambda e: e.get("concedida_em", 0), reverse=True)
