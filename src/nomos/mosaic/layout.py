"""NOMOS Mosaic — geometria do mosaico que se auto-organiza.

Regra simples e determinística: dadas N telas, o painel escolhe o menor grid
"quase quadrado" que cabe todas — 1→1×1, 2→1×2, 3/4→2×2, 5..9→3×3, ..16→4×4.
Puro (sem I/O, sem rede): fácil de testar e de renderizar em CSS grid.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Grid:
    n: int
    rows: int
    cols: int

    @property
    def cells(self) -> int:
        return self.rows * self.cols


def grid_for(n: int) -> Grid:
    """Menor grade quase-quadrada para N telas (auto-organização)."""
    if n < 0:
        raise ValueError("n não pode ser negativo")
    if n == 0:
        return Grid(0, 0, 0)
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    return Grid(n, rows, cols)


def positions(n: int) -> list[tuple[int, int]]:
    """(linha, coluna) de cada tela, preenchendo da esquerda p/ direita, cima→baixo."""
    g = grid_for(n)
    return [(i // g.cols, i % g.cols) for i in range(n)] if g.cols else []
