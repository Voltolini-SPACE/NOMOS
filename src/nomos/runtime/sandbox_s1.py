"""NOMOS runtime.sandbox_s1 — execução em container rootless (nível S1).

Garantias S1:
- runtime rootless (podman preferido; docker aceito) — sem runtime, RECUSA
  fail-closed (IsolationUnavailable): jamais degrada silenciosamente para S0;
- filesystem efêmero: --rm, --read-only, /tmp em tmpfs;
- privilégio mínimo: --cap-drop=ALL, --security-opt=no-new-privileges;
- limites de recursos: memória, pids, cpus;
- ambiente MINIMAL (nenhuma variável do host é herdada);
- rede NEGADA por padrão (--network=none);
- egress por ALLOWLIST: com allow_hosts, o container recebe rede + somente
  CAP_NET_ADMIN/NET_RAW para um prelúdio que resolve os hosts permitidos,
  aplica política iptables OUTPUT DROP (exceto lo e IP:porta permitidos)
  e só então executa o payload — nada fora da lista sai do container;
- stdout/stderr passam pelo redator de segredos por padrão.
"""
from __future__ import annotations

import re
import shlex
import shutil
import subprocess  # nosec B404 - execução em container é o propósito do S1
from dataclasses import dataclass, field

from nomos.kernel.audit import redact_text
from nomos.runtime.sandbox import IsolationUnavailable, SandboxResult

DEFAULT_IMAGE = "docker.io/library/alpine:3.20"
_HOSTPORT_RE = re.compile(r"^(?=.{1,253}:)[a-z0-9]([a-z0-9.-]*[a-z0-9])?:(\d{1,5})$")


@dataclass(frozen=True)
class S1Spec:
    cmd: str
    image: str = DEFAULT_IMAGE
    timeout: int = 60
    memory_mb: int = 256
    pids: int = 64
    cpus: float = 1.0
    allow_hosts: tuple[str, ...] = field(default_factory=tuple)  # "host:porta"


def detect_runtime() -> str | None:
    """Runtime disponível, em ordem de preferência. None = indisponível."""
    for name in ("podman", "docker"):
        if shutil.which(name):
            return name
    return None


def validate_allowlist(entries: tuple[str, ...]) -> list[tuple[str, int]]:
    """Valida 'host:porta'. Sem curingas, sem esquemas, porta 1..65535."""
    out: list[tuple[str, int]] = []
    for raw in entries:
        e = raw.strip().lower()
        m = _HOSTPORT_RE.match(e)
        if not m or "*" in e or "/" in e:
            raise ValueError(f"entrada de allowlist inválida: {raw!r} (use host:porta)")
        port = int(m.group(2))
        if not 1 <= port <= 65535:
            raise ValueError(f"porta fora de faixa em {raw!r}")
        out.append((e.rsplit(":", 1)[0], port))
    return out


def build_prelude(allow: list[tuple[str, int]]) -> str:
    """Prelúdio shell: resolve allowlist, aplica OUTPUT DROP, executa payload.

    A resolução DNS ocorre ANTES do DROP; depois dela, somente lo e os pares
    IP:porta permitidos têm saída. Falha em resolver ou aplicar regra = aborta
    (fail-closed) sem executar o payload.
    """
    lines = [
        "set -eu",
        "apk add --no-cache -q iptables >/dev/null 2>&1 || true",
        "command -v iptables >/dev/null || { echo 'NOMOS_S1: iptables ausente na imagem' >&2; exit 97; }",
        "ALLOW=''",
    ]
    for host, port in allow:
        lines += [
            f"IPS=$(getent ahostsv4 {shlex.quote(host)} | awk '{{print $1}}' | sort -u)",
            f"[ -n \"$IPS\" ] || {{ echo 'NOMOS_S1: falha ao resolver {host}' >&2; exit 98; }}",
            f"for ip in $IPS; do ALLOW=\"$ALLOW $ip:{port}\"; done",
        ]
    lines += [
        "iptables -P OUTPUT DROP",
        "iptables -A OUTPUT -o lo -j ACCEPT",
        "iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT",
        "for pair in $ALLOW; do ip=${pair%:*}; port=${pair##*:}; "
        "iptables -A OUTPUT -d \"$ip\" -p tcp --dport \"$port\" -j ACCEPT; done",
        "exec /bin/sh -c \"$NOMOS_PAYLOAD\"",
    ]
    return "\n".join(lines)


def build_args(spec: S1Spec, runtime: str) -> list[str]:
    """Constrói argv do container com defaults endurecidos (função pura)."""
    allow = validate_allowlist(spec.allow_hosts)
    argv = [
        runtime, "run", "--rm",
        "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",  # nosec B108 - tmpfs efêmero DENTRO do container
        "--security-opt", "no-new-privileges",
        "--cap-drop", "ALL",
        "--pids-limit", str(spec.pids),
        "--memory", f"{spec.memory_mb}m",
        "--cpus", str(spec.cpus),
        "--env", "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "--env", "LANG=C.UTF-8",
        "--env", "HOME=/tmp",
        "--workdir", "/tmp",  # nosec B108 - workdir dentro do container isolado
    ]
    if not allow:
        argv += ["--network", "none", spec.image, "/bin/sh", "-c", spec.cmd]
        return argv
    # Allowlist: rede ligada + capacidades mínimas p/ firewall interno do próprio netns
    argv += [
        "--cap-add", "NET_ADMIN", "--cap-add", "NET_RAW",
        "--env", f"NOMOS_PAYLOAD={spec.cmd}",
        spec.image, "/bin/sh", "-c", build_prelude(allow),
    ]
    return argv


def run(spec: S1Spec, redact_output: bool = True) -> SandboxResult:
    runtime = detect_runtime()
    if runtime is None:
        raise IsolationUnavailable(
            "nenhum runtime de container rootless (podman/docker) disponível: "
            "recuso executar S1 sem isolamento garantido (fail-closed). "
            "Instale Podman rootless ou use o nível S0."
        )
    argv = build_args(spec, runtime)
    timed_out = False
    try:
        proc = subprocess.run(  # nosec B603 - argv de container montado por build_args, sem shell
            argv, capture_output=True, text=True, timeout=spec.timeout
        )
        rc, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out, rc = True, -9
        out = (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        err = (exc.stderr or b"").decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
    if redact_output:
        out, err = redact_text(out), redact_text(err)
    return SandboxResult(
        rc=rc, stdout=out, stderr=err, timed_out=timed_out,
        network_isolated=not spec.allow_hosts,
    )
