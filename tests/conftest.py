import pytest


@pytest.fixture(autouse=True)
def _sem_modelo_do_operador(monkeypatch):
    """O shell do operador pode exportar NOMOS_OLLAMA_MODEL (ex.: mitigação de
    produção em ~/.zshenv). Herdado pela suíte, ele dá um modelo REAL aos
    caminhos "sem motor" e o chat passa a conversar com o Ollama VIVO da
    máquina — 5 testes viraram reféns do ambiente em 23/08. A suíte nasce sem
    o override; teste que o quiser, seta explicitamente via monkeypatch."""
    monkeypatch.delenv("NOMOS_OLLAMA_MODEL", raising=False)


@pytest.fixture()
def nomos_home(tmp_path, monkeypatch):
    home = tmp_path / "nomos-home"
    monkeypatch.setenv("NOMOS_HOME", str(home))
    return home
