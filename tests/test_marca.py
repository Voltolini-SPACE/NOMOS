from nomos.simple import marca
def test_banner_sem_cor():
    b = marca.banner({"tema":{"cor_ligada":False}})
    assert "seu agente" in b and "█" in b and "\033[" not in b
def test_banner_com_cor():
    assert "\033[" in marca.banner({"tema":{"paleta":"floresta","cor_ligada":True}})
