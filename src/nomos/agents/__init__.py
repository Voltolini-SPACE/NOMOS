"""NOMOS agents — subagentes locais governados (F3).

Lacuna confirmada na validação: até a v1.2 "agente" era só nome+personalidade.
Aqui há agentes especializados (Pesquisador, Programador, Segurança...), mas com
uma regra inegociável:

    UM AGENTE NÃO É ATALHO PARA BURLAR POLÍTICA.

Todo agente:
- declara suas ferramentas, permissões e risco máximo num manifesto;
- só acessa as ferramentas do manifesto (AgentToolBoundary);
- passa TODA ação pelo mesmo `policy.gate` A0–A6 do kernel — não há gate novo;
- não herda permissões de outro agente;
- tem trilha de auditoria e escopo de memória próprios.
"""
from nomos.agents.manifest import AgentManifest
from nomos.agents.registry import AgentRegistry

__all__ = ["AgentManifest", "AgentRegistry"]
