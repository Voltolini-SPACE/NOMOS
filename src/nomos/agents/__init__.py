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

Status atual (achado P2-6, auditoria de 2026-07-17): o CATÁLOGO de agentes
(manifesto, registro, sugestão por keyword) está em produção — é o que
alimenta a aba "Agentes" do painel e `nomos agentes`. A EXECUÇÃO de
ferramentas por agente via `AgentToolBoundary` está pronta e testada, mas
ainda não é chamada por nenhum fluxo real (o chat hoje roteia para
personalidade/prompt, não para chamada de ferramenta) — ver
`agents/boundary.py` para o detalhe, e `nomos doutor` para o estado ao vivo.
"""
from nomos.agents.manifest import AgentManifest
from nomos.agents.registry import AgentRegistry

__all__ = ["AgentManifest", "AgentRegistry"]
