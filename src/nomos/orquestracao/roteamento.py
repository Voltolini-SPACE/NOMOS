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


def _texto_roteavel(valor) -> list[str]:
    """Strings de um param, recursivamente (dict/list inclusos)."""
    if isinstance(valor, str):
        return [valor]
    if isinstance(valor, dict):
        saida: list[str] = []
        for v in valor.values():
            saida.extend(_texto_roteavel(v))
        return saida
    if isinstance(valor, (list, tuple, set)):
        saida = []
        for v in valor:
            saida.extend(_texto_roteavel(v))
        return saida
    return []


def _texto_do_no(no) -> str:
    """Texto a classificar = TUDO que o executor vai receber.

    Achado da auditoria adversarial: a versão anterior lia só 5 chaves
    preferidas e caía no resto apenas se elas nada rendessem — bastava uma
    chave benigna (`texto`) ao lado do segredo (`anexo`) para o classificador
    de sensibilidade ficar cego e a nuvem voltar a ser elegível. Valores
    aninhados também nunca eram lidos. O executor recebe o dict inteiro, logo
    a classificação tem de ver o dict inteiro.
    """
    partes: list[str] = []
    for valor in no.params.values():
        partes.extend(_texto_roteavel(valor))
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
