"""NOMOS pdp.aprovacao — a aprovação vincula o humano à operação EXATA (P1).

O censo adversarial do G1 provou que o gate era cego. O prompt do operador
dizia, literalmente:

    A5 · executar código | alvo='orquestracao:h:script-rodar:'

Sem comando, sem argumentos, sem arquivo, sem escopo. Um plano benigno e um
plano que exfiltrava chave privada produziam prompts **byte-idênticos**, porque
o único campo variável era o id do nó — que quem escreve o plano escolhe. O
operador digitava "APROVO" para uma abstração.

Um gate que não mostra o efeito não é consentimento informado. E mostrar não
basta: se a UI exibe A e o sistema executa B, a assinatura vale para B.

## O que este módulo garante

    OperacaoAprovavel  →  digest canônico  →  humano vê os campos REAIS
                                           →  runtime RECALCULA o digest
                                              imediatamente antes de executar
                                           →  divergiu? recusa

O digest cobre tudo que define a autoridade da operação:

    sujeito · capacidade · recurso · escopo_dados · escopo_controle
    argumentos canonizados · classe_de_risco · versao_da_politica
    digest_do_plano · expiracao · id_da_aprovacao

Trocar QUALQUER um deles depois do "APROVO" muda o digest, e o runtime recusa.
Não é uma lista de campos "que resolvemos conferir": é a definição do que foi
aprovado. Campo fora do digest é campo que o plano pode trocar depois.

## Por que uso única e prazo

Aprovação sem uso único é replay: o mesmo "APROVO" autorizaria a mesma operação
mil vezes. Aprovação sem prazo é autoridade eterna — o modelo já recusa isso
para autorização de sessão, e não haveria por que ser mais frouxo justamente
onde um humano foi consultado.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


class ErroAprovacao(RuntimeError):
    """Aprovação ausente, divergente, expirada ou reusada — sempre fail-closed."""


def _canonizar(valor):
    """Forma estável e recursiva. Dict com ordem diferente é o MESMO dict.

    Sem canonização recursiva, `{"a":1,"b":2}` e `{"b":2,"a":1}` teriam digests
    diferentes e o operador seria consultado de novo por nada — ou, pior, uma
    reordenação passaria a valer como operação distinta.
    """
    if isinstance(valor, dict):
        return {str(k): _canonizar(valor[k]) for k in sorted(valor, key=str)}
    if isinstance(valor, (list, tuple)):
        return [_canonizar(v) for v in valor]
    if isinstance(valor, (str, int, float, bool)) or valor is None:
        return valor
    return f"<{type(valor).__name__}>"          # tipo opaco não vira texto livre


@dataclass(frozen=True)
class OperacaoAprovavel:
    """A operação que o humano vê — e a única que poderá ser executada."""
    sujeito: str
    capacidade: str
    recurso: str
    classe_de_risco: str
    argumentos: dict = field(default_factory=dict)
    escopo_dados: tuple[str, ...] = ()
    escopo_controle: tuple[str, ...] = ()
    versao_da_politica: str = ""
    digest_do_plano: str = ""

    def canonico(self) -> dict:
        return {
            "sujeito": self.sujeito,
            "capacidade": self.capacidade,
            "recurso": self.recurso,
            "classe_de_risco": self.classe_de_risco,
            "argumentos": _canonizar(dict(self.argumentos)),
            "escopo_dados": sorted(self.escopo_dados),
            "escopo_controle": sorted(self.escopo_controle),
            "versao_da_politica": self.versao_da_politica,
            "digest_do_plano": self.digest_do_plano,
        }

    def digest(self) -> str:
        bruto = json.dumps(self.canonico(), sort_keys=True,
                           separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(bruto.encode("utf-8")).hexdigest()

    def descrever(self) -> str:
        """O que o operador LÊ. Os mesmos campos que o digest cobre.

        Se esta função e `canonico()` divergirem, a UI mostra A e o sistema
        assina B — exatamente o defeito que este módulo existe para fechar.
        `test_p1_descricao_cobre_os_campos_do_digest` prende as duas.
        """
        c = self.canonico()
        linhas = [
            f"sujeito:     {c['sujeito']}",
            f"capacidade:  {c['capacidade']}  (risco {c['classe_de_risco']})",
            f"recurso:     {c['recurso'] or '(nenhum)'}",
            f"argumentos:  {json.dumps(c['argumentos'], ensure_ascii=False, sort_keys=True)}",
            f"escopo dados:    {', '.join(c['escopo_dados']) or '(nenhum)'}",
            f"escopo controle: {', '.join(c['escopo_controle']) or '(nenhum)'}",
            f"política:    {c['versao_da_politica'][:16] or '(desconhecida)'}",
            f"plano:       {c['digest_do_plano'][:16] or '(avulso)'}",
        ]
        return "\n".join(linhas)


@dataclass(frozen=True)
class Aprovacao:
    """O comprovante. Vale para UM digest, UMA vez, até expirar."""
    id_aprovacao: str
    digest: str
    concedida_em: datetime
    expira_em: datetime

    def valida_em(self, agora: datetime) -> bool:
        return self.concedida_em <= agora < self.expira_em


class RegistroAprovacoes:
    """Guarda aprovações concedidas. Uso único e prazo, por construção."""

    def __init__(self, ttl_s: int = 300,
                 agora_fn=lambda: datetime.now(timezone.utc)):
        self._ttl = timedelta(seconds=max(1, int(ttl_s)))
        self._agora = agora_fn
        self._lock = threading.Lock()
        self._por_digest: dict[str, Aprovacao] = {}
        self._consumidos: set[str] = set()

    def conceder(self, operacao: OperacaoAprovavel) -> Aprovacao:
        agora = self._agora()
        ap = Aprovacao(id_aprovacao=secrets.token_hex(8),
                       digest=operacao.digest(), concedida_em=agora,
                       expira_em=agora + self._ttl)
        with self._lock:
            self._por_digest[ap.digest] = ap
        return ap

    def consumir(self, operacao: OperacaoAprovavel) -> Aprovacao:
        """Recalcula o digest da operação EFETIVA e consome a aprovação.

        Chamado imediatamente antes do efeito. É aqui que a substituição de
        alvo, argumento, capacidade, sujeito, escopo ou política morre: o
        digest recalculado simplesmente não é o que foi aprovado.
        """
        digest = operacao.digest()
        agora = self._agora()
        with self._lock:
            if digest in self._consumidos:
                raise ErroAprovacao(
                    "aprovação já usada — um 'APROVO' autoriza UMA execução")
            ap = self._por_digest.get(digest)
            if ap is None:
                raise ErroAprovacao(
                    "nenhuma aprovação para esta operação: o que será "
                    "executado não é o que foi aprovado")
            if not ap.valida_em(agora):
                self._por_digest.pop(digest, None)
                raise ErroAprovacao("aprovação expirada")
            self._por_digest.pop(digest, None)
            self._consumidos.add(digest)
        return ap


def versao_da_politica(policy) -> str:
    """Impressão digital das REGRAS vigentes.

    Entra no digest porque a política é parte do que o humano aprovou: um
    "APROVO" dado sob `A6=DENY` não pode continuar valendo depois que alguém
    mudou a regra para `ALLOW`. Sem este campo, a aprovação sobreviveria à
    mudança da premissa que a justificou.
    """
    try:
        regras = policy.rules()
    except Exception:
        return ""
    bruto = json.dumps(_canonizar(regras), sort_keys=True,
                       separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()
