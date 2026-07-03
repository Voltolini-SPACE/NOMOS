"""NOMOS runtime.sandbox — execução isolada de código (nível S0).

Garantias S0:
- ambiente MINIMAL: nenhum segredo/variável do host é herdado;
- limites de recursos (CPU, tamanho de arquivo, descritores);
- timeout de parede com kill do grupo de processos;
- rede NEGADA por padrão via user+net namespaces (unshare -rn);
- fail-closed: se o isolamento de rede não puder ser garantido e a rede
  estiver proibida, a execução é RECUSADA (IsolationUnavailable) — nunca
  executa "sem querer" com rede aberta.
"""
from __future__ import annotations

import os
try:
    import resource   # Unix-only; ausente no Windows
except ImportError:  # pragma: no cover - exercitado via simulação de SO
    resource = None
import shutil
import signal
import subprocess  # nosec B404 - execução isolada é o propósito do sandbox
import tempfile

from nomos.kernel.audit import redact_text
from dataclasses import dataclass
from functools import lru_cache


class IsolationUnavailable(Exception):
    """Isolamento de rede exigido, porém indisponível neste host."""


@dataclass(frozen=True)
class SandboxResult:
    rc: int
    stdout: str
    stderr: str
    timed_out: bool
    network_isolated: bool


@lru_cache(maxsize=1)
def netns_available() -> bool:
    unshare = shutil.which("unshare")
    if not unshare:
        return False
    try:
        probe = subprocess.run(  # nosec B603 - argv fixo (unshare), sem shell
            [unshare, "-rn", "true"], capture_output=True, timeout=5
        )
        return probe.returncode == 0
    except Exception:
        return False


def _limits(cpu_seconds: int, fsize_mb: int):
    def apply():
        if hasattr(os, "setsid"):
            os.setsid()  # novo grupo => timeout mata a árvore inteira
        if resource is not None:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
            resource.setrlimit(
                resource.RLIMIT_FSIZE, (fsize_mb * 1024 * 1024, fsize_mb * 1024 * 1024)
            )
            resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    return apply


def run(
    cmd: str | list[str],
    timeout: int = 30,
    allow_network: bool = False,
    cpu_seconds: int = 10,
    fsize_mb: int = 64,
    workdir: str | None = None,
    redact_output: bool = True,
) -> SandboxResult:
    argv = ["/bin/sh", "-c", cmd] if isinstance(cmd, str) else list(cmd)

    isolated = False
    if not allow_network:
        if not netns_available():
            raise IsolationUnavailable(
                "user namespaces indisponíveis: recuso executar com garantia de "
                "rede negada ausente (fail-closed). Aprove explicitamente "
                "allow_network=True via política ou habilite unshare/rootless."
            )
        argv = [shutil.which("unshare"), "-rn", "--", *argv]
        isolated = True

    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": "/tmp"}  # nosec B108 - HOME efêmero dentro do processo isolado
    cwd = workdir or tempfile.mkdtemp(prefix="nomos-sbx-")

    proc = subprocess.Popen(  # nosec B603 - argv construído localmente, sem shell
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=cwd,
        preexec_fn=_limits(cpu_seconds, fsize_mb) if os.name == "posix" else None,
        text=True,
    )
    timed_out = False
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            if hasattr(os, "killpg"):
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
        except ProcessLookupError:
            pass
        out, err = proc.communicate()
    out, err = out or "", err or ""
    if redact_output:
        out, err = redact_text(out), redact_text(err)
    return SandboxResult(
        rc=proc.returncode,
        stdout=out,
        stderr=err,
        timed_out=timed_out,
        network_isolated=isolated,
    )
