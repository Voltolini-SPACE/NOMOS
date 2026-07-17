"""NOMOS agents.boundary — a fronteira de ferramentas + o gate compartilhado (F3).

Este módulo é a garantia de que "agente não é bypass":
- `AgentToolBoundary.permitido(ferramenta)` só devolve True se a ferramenta
  estiver no manifesto do agente — nada de acesso implícito;
- `usar_ferramenta` decide pela categoria de política da ferramenta e passa
  pelo MESMO `policy.gate` do kernel. Sem aprovação/TTY => negado (fail-closed).
Nenhum caminho novo de autorização é criado aqui.

Status de integração (achado P2-6, auditoria de 2026-07-17): esta classe é
totalmente implementada e testada em isolamento, mas HOJE nenhum fluxo real
de produção a instancia — o roteamento de agente (`AgentRegistry.sugerir`,
usado por `cli.py`/`painel_web.py`) escolhe personalidade/prompt, não chama
ferramentas. Não é um bug: enquanto não existir chamada de ferramenta por
agente, não há nada para este gate proteger em produção ainda. `nomos
doutor` reporta esse estado (não-bloqueante). Wiring real de produção é
trabalho de escopo maior, fora deste achado — ver Horizonte 3/P3 do plano
de melhorias.
"""
from __future__ import annotations

from nomos.agents.manifest import FERRAMENTAS, AgentManifest
from nomos.kernel.policy import Category, gate


class AgentToolBoundary:
    def __init__(self, manifesto: AgentManifest, policy, approver, audit=None):
        self.mf = manifesto
        self.policy = policy
        self.approver = approver
        self.audit = audit

    def permitido(self, ferramenta: str) -> bool:
        return ferramenta in self.mf.ferramentas

    def usar_ferramenta(self, ferramenta: str, executar, alvo: str = "") -> tuple[bool, object]:
        """(ok, resultado). Fora do manifesto => negado. Dentro => passa pelo gate."""
        if not self.permitido(ferramenta):
            if self.audit is not None:
                self.audit.append("agente.ferramenta.negada", agente=self.mf.name,
                                  ferramenta=ferramenta, motivo="fora do manifesto")
            return False, (f"o agente '{self.mf.name}' não tem a ferramenta "
                           f"'{ferramenta}' no manifesto")
        categoria: Category = FERRAMENTAS[ferramenta]
        decisao = self.policy.decide(categoria,
                                     target=f"agente:{self.mf.name}:{ferramenta}:{alvo}")
        if not gate(decisao, self.approver):
            if self.audit is not None:
                self.audit.append("agente.ferramenta.gate_negou", agente=self.mf.name,
                                  ferramenta=ferramenta,
                                  categoria=categoria.value, motivo=decisao.reason)
            return False, (f"'{ferramenta}' precisa de aprovação ({categoria.value}) "
                           f"e foi negada: {decisao.reason}")
        if self.audit is not None:
            self.audit.append("agente.ferramenta.usada", agente=self.mf.name,
                              ferramenta=ferramenta, categoria=categoria.value)
        try:
            return True, executar()
        except Exception as exc:
            return False, f"ferramenta '{ferramenta}' falhou: {type(exc).__name__}"
