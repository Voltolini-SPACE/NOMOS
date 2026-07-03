import pytest


@pytest.fixture()
def nomos_home(tmp_path, monkeypatch):
    home = tmp_path / "nomos-home"
    monkeypatch.setenv("NOMOS_HOME", str(home))
    return home
