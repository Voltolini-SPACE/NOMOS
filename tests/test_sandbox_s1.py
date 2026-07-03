"""C2 — Sandbox S1: fail-closed sem runtime, defaults endurecidos, allowlist."""
import shutil

import pytest

from nomos.runtime import sandbox_s1 as s1
from nomos.runtime.sandbox import IsolationUnavailable


def test_sem_runtime_recusa_fail_closed(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _: None)
    assert s1.detect_runtime() is None
    with pytest.raises(IsolationUnavailable, match="podman/docker"):
        s1.run(s1.S1Spec(cmd="echo oi"))


def test_defaults_endurecidos_sem_rede():
    argv = s1.build_args(s1.S1Spec(cmd="echo oi"), runtime="podman")
    joined = " ".join(argv)
    for token in (
        "--rm", "--read-only", "--cap-drop ALL", "--security-opt no-new-privileges",
        "--pids-limit 64", "--memory 256m", "--network none", "--tmpfs",
    ):
        assert token in joined, f"faltou: {token}"
    assert "NET_ADMIN" not in joined          # sem allowlist, sem capacidade extra


def test_ambiente_nao_herda_host(monkeypatch):
    monkeypatch.setenv("SEGREDO_DO_HOST", "sk-vazou-9999999999")
    argv = s1.build_args(s1.S1Spec(cmd="env"), runtime="podman")
    assert "SEGREDO_DO_HOST" not in " ".join(argv)
    envs = [argv[i + 1] for i, a in enumerate(argv) if a == "--env"]
    assert all(e.split("=")[0] in {"PATH", "LANG", "HOME"} for e in envs)


@pytest.mark.parametrize("ruim", [
    "sem-porta", "host:0", "host:70000", "*.example.com:443",
    "http://x.com:80", "a b:80", "host:abc",
])
def test_allowlist_invalida(ruim):
    with pytest.raises(ValueError):
        s1.validate_allowlist((ruim,))


def test_allowlist_valida_e_prelude_drop():
    allow = s1.validate_allowlist(("api.anthropic.com:443", "pypi.org:443"))
    assert allow == [("api.anthropic.com", 443), ("pypi.org", 443)]
    prelude = s1.build_prelude(allow)
    assert "iptables -P OUTPUT DROP" in prelude
    assert "api.anthropic.com" in prelude and "pypi.org" in prelude
    assert prelude.index("getent") < prelude.index("OUTPUT DROP")  # resolve antes do DROP
    assert "exit 98" in prelude                                    # resolução falhou = aborta


def test_allowlist_liga_rede_com_cap_minima():
    spec = s1.S1Spec(cmd="curl -s https://pypi.org", allow_hosts=("pypi.org:443",))
    argv = s1.build_args(spec, runtime="podman")
    joined = " ".join(argv)
    assert "--network none" not in joined
    assert "NET_ADMIN" in joined and "NET_RAW" in joined
    assert "--cap-drop ALL" in joined         # drop ALL continua; só as duas voltam
    assert "NOMOS_PAYLOAD=curl -s https://pypi.org" in joined
