import pytest

from nomos.kernel import config
from nomos.simple import tema


def test_aplicar_paleta_persiste(nomos_home):
    config.ensure_home()
    tema.aplicar(paleta="floresta")
    assert tema.carregar(config.load_agent()).destaque == "verde"


def test_destaque_customizado(nomos_home):
    config.ensure_home()
    tema.aplicar(destaque="rosa")
    assert tema.carregar(config.load_agent()).destaque == "rosa"


def test_paleta_invalida(nomos_home):
    with pytest.raises(ValueError):
        tema.aplicar(paleta="arco-iris")


def test_cor_invalida(nomos_home):
    with pytest.raises(ValueError):
        tema.aplicar(destaque="turquesa")


def test_desligar_cor(nomos_home):
    config.ensure_home()
    tema.aplicar(cor_ligada=False)
    assert "\033[" not in tema.carregar(config.load_agent()).c("titulo", "X")


def test_cor_ligada(nomos_home):
    t = tema.carregar({"tema": {"paleta": "roxo", "cor_ligada": True}})
    assert "\033[" in t.c("destaque", "X")
