"""Regressão — local-first é lei: nada muda isso em v0.11."""
import pytest

from nomos.cognition import engine_catalog as cat_mod
from nomos.cognition import engine_policy as epol
from nomos.cognition import engine_router as er
from nomos.cognition import motores
from nomos.kernel import localidade
from nomos.kernel.policy import Category, Effect, PolicyEngine


@pytest.fixture(autouse=True)
def _sem_rede(monkeypatch, nomos_home):
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: [])
    monkeypatch.setattr(motores, "_http_ok", lambda *a, **k: False)
    monkeypatch.setattr("shutil.which", lambda *a, **k: None)
    motores.limpar_cache()
    yield
    motores.limpar_cache()


def test_padrao_de_fabrica_e_ligado(nomos_home):
    assert localidade.esta_ligado(nomos_home) is True   # sem arquivo => ligado


def test_arquivo_corrompido_continua_ligado(nomos_home):
    nomos_home.mkdir(parents=True, exist_ok=True)
    (nomos_home / "localidade.json").write_text("{corrompido")
    assert localidade.esta_ligado(nomos_home) is True


def test_politica_nega_egress_externo_antes_do_gate(nomos_home):
    engine = PolicyEngine(nomos_home / "policy.json")
    d = engine.decide(Category.NET_EGRESS, target="api.anthropic.com")
    assert d.effect is Effect.DENY
    # loopback (motor local) não é egress externo
    d2 = engine.decide(Category.NET_EGRESS, target="http://127.0.0.1:11434")
    assert d2.effect is not Effect.DENY


def test_modo_local_bloqueia_cloud_no_catalogo(nomos_home):
    nuvem = cat_mod.construir(nomos_home).por_id("anthropic")
    assert nuvem.pronto is False


def test_modo_local_bloqueia_cloud_no_roteador(nomos_home):
    dec = er.rotear(er.Tarefa("conversa", "texto"), home=nomos_home,
                    chave_configurada=True)
    assert dec.selected_engine != "anthropic"
    assert dec.fallback_engine != "anthropic"


def test_elegibilidade_cloud_negada_com_cadeado(nomos_home):
    nuvem = cat_mod.construir(nomos_home).por_id("anthropic")
    e = epol.elegivel(nuvem, nomos_home)
    assert e.ok is False and "só-local" in e.motivo


def test_religar_cadeado_sempre_permitido(nomos_home):
    localidade.definir(nomos_home, False)
    assert localidade.esta_ligado(nomos_home) is False
    localidade.definir(nomos_home, True)    # voltar ao seguro nunca é barrado
    assert localidade.esta_ligado(nomos_home) is True


def test_roteador_prefere_local_mesmo_com_nuvem_plugada(monkeypatch, nomos_home):
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: ["hermes3:8b"])
    motores.limpar_cache()
    localidade.definir(nomos_home, False)   # nuvem plugada
    dec = er.rotear(er.Tarefa("conversa", "texto"), home=nomos_home,
                    chave_configurada=True)
    assert dec.selected_engine == "ollama"  # local vence sempre que existe
    assert dec.local_only_preserved is True
