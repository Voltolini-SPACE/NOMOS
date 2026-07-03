"""Fase 3 — catálogo de motores v0.11: 12 modalidades e atributos honestos."""
import pytest

from nomos.cognition import engine_catalog as cat_mod
from nomos.cognition import motores
from nomos.kernel import localidade


@pytest.fixture(autouse=True)
def _sem_rede(monkeypatch, nomos_home):
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: [])
    monkeypatch.setattr(motores, "_http_ok", lambda *a, **k: False)
    monkeypatch.setattr("shutil.which", lambda *a, **k: None)
    motores.limpar_cache()
    yield
    motores.limpar_cache()


def test_doze_modalidades():
    assert len(cat_mod.MODALIDADES_V011) == 12
    for m in ("texto", "codigo", "raciocinio", "resumo", "memoria", "voz_stt",
              "voz_tts", "imagem", "visao", "embeddings", "ferramentas",
              "roteamento"):
        assert m in cat_mod.MODALIDADES_V011


def test_sempre_locais_prontos(nomos_home):
    cat = cat_mod.construir(nomos_home)
    for mod in ("memoria", "embeddings", "roteamento"):
        prontos = cat.prontos(mod)
        assert prontos and all(m.local for m in prontos)


def test_atributos_do_motor_cloud(nomos_home):
    cat = cat_mod.construir(nomos_home)
    nuvem = cat.por_id("anthropic")
    assert nuvem.tipo == "cloud" and not nuvem.local
    assert nuvem.requer_chave and nuvem.requer_aprovacao
    assert nuvem.custo == "pago por uso"
    assert "saem da máquina" in nuvem.privacidade
    # cadeado ligado (padrão) => nuvem não está "pronta" nem por engano
    assert nuvem.pronto is False and "só-local" in nuvem.status


def test_cloud_pronta_apenas_com_cadeado_desligado(nomos_home):
    localidade.definir(nomos_home, False)
    cat = cat_mod.construir(nomos_home)
    assert cat.por_id("anthropic").pronto is True
    localidade.definir(nomos_home, True)
    motores.limpar_cache()
    assert cat_mod.construir(nomos_home).por_id("anthropic").pronto is False


def test_recomendar_prefere_local(monkeypatch, nomos_home):
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: ["hermes3:8b"])
    motores.limpar_cache()
    localidade.definir(nomos_home, False)   # nuvem elegível, mas local vence
    rec = cat_mod.recomendar("texto", home=nomos_home)
    assert rec is not None and rec.local and rec.id == "ollama"


def test_recomendar_sem_motor_devolve_none(nomos_home):
    assert cat_mod.recomendar("voz_stt", home=nomos_home) is None


def test_tabela_v011_mostra_atributos(nomos_home):
    texto = cat_mod.tabela_v011(home=nomos_home)
    for trecho in ("Motores do NOMOS", "privacidade", "qualidade",
                   "memoria", "roteamento", "recomendar"):
        assert trecho in texto


def test_ollama_detectado_fica_pronto(monkeypatch, nomos_home):
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: ["hermes3:8b"])
    motores.limpar_cache()
    cat = cat_mod.construir(nomos_home)
    m = cat.por_id("ollama")
    assert m.pronto and m.instalado and m.detalhe == "hermes3:8b"
    assert m.local and m.custo == "grátis"
