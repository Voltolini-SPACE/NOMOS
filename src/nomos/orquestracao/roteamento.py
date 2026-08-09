"""NOMOS orquestracao.roteamento — adaptador nó→roteador de motores (NH-007).

NÃO reimplementa roteamento: o NOMOS JÁ TEM um roteador local-first explicável
(`cognition.engine_router`, com `classificar()` + `rotear()` + política de
privacidade > feedback > qualidade > custo). Este módulo só o liga ao
orquestrador (NH-002): converte um nó do grafo em `Tarefa`, roteia e devolve
a `EngineRouteDecision`.

A decisão de rota é DADO, não autorização — a execução do nó continua passando
pelo `policy.gate` do kernel. A regra `local_only` do roteador é preservada:
dado sensível nunca escolhe nuvem.
"""
from __future__ import annotations

from typing import Callable

from nomos.cognition import engine_router as er


def _texto_do_no(no) -> str:
    """Extrai o texto roteável dos params (sem inventar; concatena valores str)."""
    partes = []
    for chave in ("texto", "prompt", "objetivo", "conteudo", "pergunta"):
        v = no.params.get(chave)
        if isinstance(v, str):
            partes.append(v)
    if not partes:                     # fallback: qualquer valor textual
        partes = [v for v in no.params.values() if isinstance(v, str)]
    return " ".join(partes)


def roteador_de_no(home=None,
                   chave_configurada: bool | None = None) -> Callable:
    """Devolve `rotear_motor(no) -> EngineRouteDecision` para o Orquestrador.

    `home` e `chave_configurada` são repassados ao roteador existente sem
    alterar o contrato dele (local-first, gate na hora do uso continua fora)."""

    def _rotear(no) -> er.EngineRouteDecision:
        texto = _texto_do_no(no)
        tarefa = er.classificar(texto)
        return er.rotear(tarefa, home=home, chave_configurada=chave_configurada)

    return _rotear
