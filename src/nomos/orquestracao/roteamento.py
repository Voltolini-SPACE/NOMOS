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

from dataclasses import replace
from typing import Callable

from nomos.cognition import engine_router as er


_PROFUNDIDADE_MAX = 12
_NOS_MAX = 5000


def _str_segura(valor) -> str:
    try:
        return str(valor)
    except Exception:
        return ""


def _texto_roteavel(valor, _prof: int = 0, _vistos: set | None = None,
                    incompleto: list | None = None) -> list[str]:
    """Texto de um param, recursivamente — chaves, valores e escalares.

    Teto de profundidade + já-vistos por `id`: estrutura cíclica não pode
    virar `RecursionError` no meio de uma decisão de roteamento. Quando o teto
    ou um ciclo cortam a varredura, `incompleto` é marcado: inspeção parcial
    NÃO pode ser lida como "não há nada sensível aqui" (achado da rodada 2 —
    enterrar o segredo além do teto desligava a proteção).
    """
    if _vistos is None:
        _vistos = set()
    if _prof > _PROFUNDIDADE_MAX or len(_vistos) > _NOS_MAX:
        if incompleto is not None:
            incompleto.append(True)
        return []
    if isinstance(valor, str):
        return [valor]
    if isinstance(valor, (dict, list, tuple, set)):
        marca = id(valor)
        if marca in _vistos:
            if incompleto is not None:
                incompleto.append(True)
            return []
        _vistos.add(marca)
    if isinstance(valor, dict):
        saida: list[str] = []
        for k, v in valor.items():
            saida.append(_str_segura(k))          # o NOME do param também conta
            saida.extend(_texto_roteavel(v, _prof + 1, _vistos, incompleto))
        return saida
    if isinstance(valor, (list, tuple, set)):
        saida = []
        for v in valor:
            saida.extend(_texto_roteavel(v, _prof + 1, _vistos, incompleto))
        return saida
    return [_str_segura(valor)]                   # bytes/int/etc. também são dados


def _texto_e_completude(no) -> tuple[str, bool]:
    """(texto a classificar, inspeção foi completa?)."""
    partes: list[str] = []
    incompleto: list = []
    for chave, valor in no.params.items():
        partes.append(_str_segura(chave))
        partes.extend(_texto_roteavel(valor, incompleto=incompleto))
    return " ".join(partes), not incompleto


def _texto_do_no(no) -> str:
    """Texto a classificar = TUDO que o executor vai receber.

    Achado da auditoria adversarial: a versão anterior lia só 5 chaves
    preferidas e caía no resto apenas se elas nada rendessem — bastava uma
    chave benigna (`texto`) ao lado do segredo (`anexo`) para o classificador
    de sensibilidade ficar cego e a nuvem voltar a ser elegível. Valores
    aninhados também nunca eram lidos. O executor recebe o dict inteiro, logo
    a classificação tem de ver o dict inteiro.
    """
    return _texto_e_completude(no)[0]


def classificar_no(no) -> er.Tarefa:
    """Tarefa do nó, com a regra fail-closed do invariante 8: se a varredura
    dos params não foi completa (ciclo, teto de profundidade), a tarefa é
    tratada como SENSÍVEL — inspeção parcial nunca autoriza a nuvem."""
    texto, completa = _texto_e_completude(no)
    tarefa = er.classificar(texto)
    if not completa and not tarefa.dados_sensiveis:
        tarefa = replace(tarefa, dados_sensiveis=True)
    return tarefa


def roteador_de_no(home=None,
                   chave_configurada: bool | None = None) -> Callable:
    """Devolve `rotear_motor(no) -> EngineRouteDecision` para o Orquestrador.

    `home` e `chave_configurada` são repassados ao roteador existente sem
    alterar o contrato dele (local-first, gate na hora do uso continua fora)."""

    def _rotear(no) -> er.EngineRouteDecision:
        tarefa = classificar_no(no)     # fail-closed: inspeção parcial = sensível
        return er.rotear(tarefa, home=home, chave_configurada=chave_configurada)

    return _rotear
