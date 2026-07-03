import subprocess
import sys

from nomos.kernel import plataforma

_COD = '''
import builtins
_orig = builtins.__import__
def fake(n, *a, **k):
    if n == "resource":
        raise ImportError("simulando Windows")
    return _orig(n, *a, **k)
builtins.__import__ = fake
import nomos.cli
import nomos.runtime.sandbox as sb
assert sb.resource is None, "resource deveria ser None"
print("IMPORT_OK_SEM_RESOURCE")
'''


def test_helpers():
    assert set(plataforma.resumo()) == {"sistema", "python", "execucao_isolada"}


def test_chmod_privado_nunca_levanta(tmp_path):
    f = tmp_path / "x"
    f.write_text("s")
    plataforma.chmod_privado(f, 0o600)
    plataforma.chmod_privado(tmp_path / "nao-existe", 0o600)


def test_isolada_falsa_fora_linux(monkeypatch):
    monkeypatch.setattr(plataforma, "EH_LINUX", False)
    assert plataforma.execucao_isolada_disponivel() is False


def test_importa_sem_resource():
    r = subprocess.run([sys.executable, "-c", _COD], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "IMPORT_OK_SEM_RESOURCE" in r.stdout
