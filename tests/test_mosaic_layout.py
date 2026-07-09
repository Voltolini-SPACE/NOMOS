"""NOMOS Mosaic — grid auto-organizável."""
import pytest

from nomos.mosaic import layout


@pytest.mark.parametrize("n,rows,cols", [
    (1, 1, 1), (2, 1, 2), (3, 2, 2), (4, 2, 2),
    (5, 2, 3), (6, 2, 3), (9, 3, 3), (10, 3, 4), (16, 4, 4),
])
def test_grid_auto_organiza(n, rows, cols):
    g = layout.grid_for(n)
    assert (g.rows, g.cols) == (rows, cols)
    assert g.cells >= n            # sempre cabe todas as telas


def test_zero_e_negativo():
    assert layout.grid_for(0) == layout.Grid(0, 0, 0)
    with pytest.raises(ValueError):
        layout.grid_for(-1)


def test_positions_preenche_em_ordem():
    assert layout.positions(3) == [(0, 0), (0, 1), (1, 0)]
    assert layout.positions(0) == []
