"""NOMOS agents.boundary — a fronteira de ferramentas + o gate compartilhado (F3).

Este módulo é a garantia de que "agente não é bypass":
- `AgentToolBoundary.permitido(ferramenta)` só devolve True se a ferramenta
  estiver no manifesto do agente — nada de acesso implícito;
- `usar_ferramenta` decide pela categoria de política da ferramenta e passa
  pelo MESMO `policy.gate` do kernel. Sem aprovação/TTY => negado (fail-closed).
Nenhum caminho novo de autorização é criado aqui.

Status de integração (achado P2-6, Horizonte 2 -> wiring real no Horizonte 3/
item 1 -> 8/8 ferramentas na missão de eliminação de débitos residuais,
auditoria de 2026-07-17, Prioridade 1 / parte a): esta classe é totalmente
implementada e testada em isolamento, e tem um caller real de produção —
`cli.py::cmd_agente_usar` (`nomos agentes usar <agente> <ferramenta>`) —
para as 8 ferramentas da allowlist (`memoria_buscar`, `arquivo_ler`,
`arquivo_resumir`, `arquivo_escrever`, `codigo_gerar`, `doutor`,
`logs_verificar`, `skill_rodar`; ver `agents/execucao.py` para a primitiva
reaproveitada por cada uma). `AgentRegistry.sugerir` segue sem caller de
produção — é sobre ROTEAMENTO de agente por intenção no chat, item
distinto (parte b da mesma Prioridade 1). `nomos doutor` reporta o estado
ao vivo (não-bloqueante).
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
