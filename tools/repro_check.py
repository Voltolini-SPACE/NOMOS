#!/usr/bin/env python3
"""Gate hermético de reprodutibilidade — dois builds independentes,
diff se divergir.

Contrato (H4.9)
---------------
Faz dois builds em diretórios SEPARADOS, sem compartilhar venv, cache do
pip, `build/`, `dist/` ou `*.egg-info`. Cada build usa exatamente o
toolchain pinado no `release.yml`. Depois da geração, cada `.tar.gz`
passa por `tools/reproducible_sdist.py` (mesma normalização que a
release aplica). No fim, compara sha256 do wheel e do sdist entre A e B.

Saídas (impressas na última linha, um por linha, "chave=valor"):

    REPRO_WHEEL=PASS|FAIL
    REPRO_SDIST=PASS|FAIL

Se qualquer um for FAIL, o script imprime um diagnóstico da divergência
(hashes, tamanhos, primeiros membros diferentes, primeiro byte que difere)
e sai com código 1.

O source tree usado é o próprio checkout do NOMOS de onde o script foi
invocado (raiz do repo), copiado para dois diretórios distintos. Arquivos
listados em `_EXCLUDE_DIRS` NÃO são copiados — evita poluir os builds
com artefatos anteriores.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tarfile
import tempfile
import venv
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "dist",
    "build",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    "site-packages",
}

_TOOLCHAIN_PINS = [
    "setuptools==83.0.0",
    "wheel==0.45.1",
    "build==1.5.0",
    "packaging==26.3",
    "pyproject_hooks==1.2.0",
]
_PIP_PIN = "pip==26.2.1"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _copytree_pruned(src: Path, dst: Path) -> None:
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in _EXCLUDE_DIRS]
        rel = Path(root).relative_to(src)
        (dst / rel).mkdir(parents=True, exist_ok=True)
        for f in files:
            if f.endswith((".pyc", ".pyo")):
                continue
            shutil.copy2(Path(root) / f, dst / rel / f)


def _epoch_from_repo() -> str:
    r = subprocess.run(
        ["git", "log", "-1", "--pretty=%ct"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=True,
    )
    return r.stdout.strip()


def _build_one(workdir: Path, epoch: str) -> tuple[Path, Path]:
    """Constrói wheel+sdist em `workdir/src` usando venv+pipcache próprios.
    Retorna `(wheel_path, sdist_path)`.
    """
    src = workdir / "src"
    v = workdir / "venv"
    pipcache = workdir / "pipcache"
    src.mkdir(parents=True, exist_ok=True)
    pipcache.mkdir(parents=True, exist_ok=True)
    _copytree_pruned(REPO, src)
    venv.create(v, with_pip=True, clear=True)
    py = v / "bin" / "python"
    if not py.exists():  # Windows
        py = v / "Scripts" / "python.exe"
    env = {
        **os.environ,
        "SOURCE_DATE_EPOCH": epoch,
        "PYTHONHASHSEED": "0",
        "TZ": "UTC",
        "LC_ALL": "C.UTF-8",
        "LANG": "C.UTF-8",
        "PIP_CACHE_DIR": str(pipcache),
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    }
    subprocess.run(
        [str(py), "-m", "pip", "install", "-q", "--upgrade", _PIP_PIN],
        env=env,
        check=True,
    )
    subprocess.run(
        [str(py), "-m", "pip", "install", "-q", *_TOOLCHAIN_PINS],
        env=env,
        check=True,
    )
    subprocess.run(
        [str(py), "-m", "build", "--no-isolation"],
        cwd=str(src),
        env=env,
        check=True,
    )
    subprocess.run(
        [
            str(py),
            str(src / "tools" / "reproducible_sdist.py"),
            *[str(p) for p in (src / "dist").glob("*.tar.gz")],
        ],
        env=env,
        check=True,
    )
    wheels = list((src / "dist").glob("*.whl"))
    sdists = list((src / "dist").glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise RuntimeError(
            f"esperava 1 wheel e 1 sdist em {src/'dist'}; "
            f"vi wheels={wheels} sdists={sdists}"
        )
    return wheels[0], sdists[0]


def _diagnose_wheels(a: Path, b: Path) -> str:
    lines = [f"[wheel diff] {a.name} vs {b.name}", f"  size A={a.stat().st_size}  size B={b.stat().st_size}"]
    with zipfile.ZipFile(a) as za, zipfile.ZipFile(b) as zb:
        na = za.namelist()
        nb = zb.namelist()
        if na != nb:
            missing_b = set(na) - set(nb)
            missing_a = set(nb) - set(na)
            lines.append(f"  members only in A: {sorted(missing_b)[:5]}")
            lines.append(f"  members only in B: {sorted(missing_a)[:5]}")
            return "\n".join(lines)
        for name in na:
            infA = za.getinfo(name)
            infB = zb.getinfo(name)
            if (infA.date_time, infA.CRC, infA.file_size) != (
                infB.date_time,
                infB.CRC,
                infB.file_size,
            ):
                lines.append(
                    f"  first-diff member: {name}\n"
                    f"    A: date={infA.date_time} crc={infA.CRC:#010x} size={infA.file_size}\n"
                    f"    B: date={infB.date_time} crc={infB.CRC:#010x} size={infB.file_size}"
                )
                return "\n".join(lines)
    lines.append("  members identical but bytes differ — provavelmente ordem no ZIP ou padding")
    return "\n".join(lines)


def _diagnose_sdists(a: Path, b: Path) -> str:
    lines = [f"[sdist diff] {a.name} vs {b.name}", f"  size A={a.stat().st_size}  size B={b.stat().st_size}"]
    with tarfile.open(a) as ta, tarfile.open(b) as tb:
        na = ta.getnames()
        nb = tb.getnames()
        if na != nb:
            missing_b = set(na) - set(nb)
            missing_a = set(nb) - set(na)
            lines.append(f"  members only in A: {sorted(missing_b)[:5]}")
            lines.append(f"  members only in B: {sorted(missing_a)[:5]}")
            return "\n".join(lines)
        for m_a, m_b in zip(ta.getmembers(), tb.getmembers(), strict=True):
            if (m_a.mtime, m_a.uid, m_a.gid, m_a.uname, m_a.gname, m_a.mode) != (
                m_b.mtime,
                m_b.uid,
                m_b.gid,
                m_b.uname,
                m_b.gname,
                m_b.mode,
            ):
                lines.append(
                    f"  first-diff member: {m_a.name}\n"
                    f"    A: mtime={m_a.mtime} uid={m_a.uid} gid={m_a.gid} "
                    f"uname={m_a.uname!r} gname={m_a.gname!r} mode={m_a.mode:o}\n"
                    f"    B: mtime={m_b.mtime} uid={m_b.uid} gid={m_b.gid} "
                    f"uname={m_b.uname!r} gname={m_b.gname!r} mode={m_b.mode:o}"
                )
                return "\n".join(lines)
    lines.append("  member metadata identical — provavelmente gzip header ou compressão")
    return "\n".join(lines)


def main() -> int:
    epoch = _epoch_from_repo()
    print(f"SOURCE_DATE_EPOCH={epoch}", flush=True)
    with tempfile.TemporaryDirectory(prefix="nomos-repro-") as tmp:
        tmp_p = Path(tmp)
        print("[A] building...", flush=True)
        wa, sa = _build_one(tmp_p / "A", epoch)
        print(f"[A] wheel={wa.name}  sdist={sa.name}", flush=True)
        print("[B] building...", flush=True)
        wb, sb = _build_one(tmp_p / "B", epoch)
        print(f"[B] wheel={wb.name}  sdist={sb.name}", flush=True)

        ha_w, hb_w = _sha256(wa), _sha256(wb)
        ha_s, hb_s = _sha256(sa), _sha256(sb)

        print(f"WHEEL_A={ha_w}", flush=True)
        print(f"WHEEL_B={hb_w}", flush=True)
        print(f"SDIST_A={ha_s}", flush=True)
        print(f"SDIST_B={hb_s}", flush=True)

        wheel_ok = ha_w == hb_w
        sdist_ok = ha_s == hb_s

        if not wheel_ok:
            print(_diagnose_wheels(wa, wb), flush=True)
        if not sdist_ok:
            print(_diagnose_sdists(sa, sb), flush=True)

        print(f"REPRO_WHEEL={'PASS' if wheel_ok else 'FAIL'}", flush=True)
        print(f"REPRO_SDIST={'PASS' if sdist_ok else 'FAIL'}", flush=True)
        return 0 if (wheel_ok and sdist_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
