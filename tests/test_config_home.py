"""MC46.3 — nomos_home() não depende de Path.home() quando NOMOS_HOME existe.

Regressão real do Windows: o default de ``os.environ.get`` era avaliado de
forma ansiosa, então ``Path.home()`` rodava mesmo com NOMOS_HOME setado —
e num ambiente sem as variáveis de home (ex.: subprocesso no Windows sem
USERPROFILE) estourava com "Could not determine home directory".
"""
from pathlib import Path

from nomos.kernel import config


def test_nomos_home_usa_env_sem_tocar_path_home(monkeypatch, tmp_path):
    monkeypatch.setenv("NOMOS_HOME", str(tmp_path / "meu-nomos"))

    def _explode():
        raise RuntimeError("Could not determine home directory.")

    # com NOMOS_HOME definido, Path.home() NÃO pode ser chamado
    monkeypatch.setattr(Path, "home", staticmethod(_explode))
    assert config.nomos_home() == Path(str(tmp_path / "meu-nomos"))


def test_nomos_home_cai_no_default_sem_env(monkeypatch, tmp_path):
    monkeypatch.delenv("NOMOS_HOME", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert config.nomos_home() == tmp_path / ".nomos"
