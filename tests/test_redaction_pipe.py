"""C2 — redator de segredos no pipe stdout/stderr do sandbox (risco #4)."""
import pytest

from nomos.kernel.audit import REDACTED, redact_text
from nomos.runtime import sandbox


def _netns():
    return sandbox.netns_available()


def test_redact_text_padroes():
    s = "token sk-abcdef123456789 e AKIAABCDEFGHIJKLMNOP e Bearer abc.def-ghi_jkl"
    out = redact_text(s)
    assert "sk-abcdef" not in out and "AKIA" not in out and "Bearer abc" not in out
    assert out.count(REDACTED) == 3


@pytest.mark.skipif(not _netns(), reason="exige user+net namespaces")
def test_stdout_do_sandbox_e_redigido_por_padrao():
    r = sandbox.run("echo vazei sk-abcdefghijklmnop0001; echo err AKIAABCDEFGHIJKLMNOP >&2")
    assert r.rc == 0
    assert "sk-abcdefghijklmnop0001" not in r.stdout
    assert REDACTED in r.stdout
    assert "AKIA" not in r.stderr and REDACTED in r.stderr


@pytest.mark.skipif(not _netns(), reason="exige user+net namespaces")
def test_opt_out_explicito_devolve_cru():
    r = sandbox.run("echo cru sk-abcdefghijklmnop0002", redact_output=False)
    assert "sk-abcdefghijklmnop0002" in r.stdout
