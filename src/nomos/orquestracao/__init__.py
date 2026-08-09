"""NOMOS orquestracao — orquestração governada de execução (missão NH).

Convergência NOMOS×HERMES (NOMOS-HERMES-CAPABILITY-GAP-01): o NOMOS ganha a
estrutura de controle de execução que faltava — registro dinâmico de
capacidades (NH-001), grafo de tarefas com dependências (NH-002), planejador
tipado (NH-003) e recuperação com circuit-breaker (NH-004) — integrada ao
roteador de motores já existente (`cognition.engine_router`, NH-007).

Regra inegociável (a mesma de agents/): ORQUESTRAR NÃO É ATALHO PARA BURLAR
POLÍTICA. Todo nó passa pelo MESMO `policy.gate` A0–A6 do kernel antes de
executar; capacidade desconhecida é negada; negação bloqueia dependentes;
nenhum caminho novo de autorização é criado aqui.
"""
from nomos.orquestracao.grafo import (
    ErroGrafo, GrafoTarefas, No, Orquestrador, ResultadoMissao, ResultadoNo,
)
from nomos.orquestracao.planejador import PassoTipado, PlanoTipado, planejar
from nomos.orquestracao.recuperacao import (
    GerenciadorRecuperacao, PoliticaRecuperacao,
)
from nomos.orquestracao.registro import Capacidade, ErroRegistro, RegistroCapacidades

# `roteamento` fica FORA deste __init__ de propósito: ele importa
# `cognition.engine_router` (catálogo de motores, política, localidade), que é
# bem mais pesado que o resto do pacote. Quem precisa de roteamento importa
# explicitamente `from nomos.orquestracao.roteamento import roteador_de_no`.
__all__ = [
    "Capacidade", "ErroRegistro", "RegistroCapacidades",
    "No", "GrafoTarefas", "Orquestrador", "ErroGrafo",
    "ResultadoNo", "ResultadoMissao",
    "planejar", "PlanoTipado", "PassoTipado",
    "GerenciadorRecuperacao", "PoliticaRecuperacao",
]
