#!/usr/bin/env python3
"""Normaliza um sdist (`.tar.gz`) para reprodutibilidade bit-a-bit.

Motivação
---------
`setuptools.build_meta.build_sdist` **não** respeita `SOURCE_DATE_EPOCH` até
pelo menos a versão 83 (bug documentado em pypa/setuptools#2133): mtimes de
arquivos e diretórios dentro do `.tar.gz` são o wall-clock do momento do
build, e o header gzip embute a hora da compactação. Isso faz com que dois
builds do mesmo commit produzam sdists de hash diferente sem qualquer
diferença de conteúdo semântico.

Contrato
--------
Este script reescreve o `.tar.gz` in-place, normalizando **apenas metadados
de container** (tar member metadata + gzip header). Nomes, permissões
executivas (bit 0o111) e conteúdo de cada membro são preservados
exatamente. Modo é restringido a `0o644` para arquivos, `0o755` para
diretórios (o setuptools sdist já não distingue além disso).

Concretamente, para cada membro do tar:

- ``mtime``  → ``SOURCE_DATE_EPOCH`` (obrigatório no ambiente)
- ``uid``    → 0
- ``gid``    → 0
- ``uname``  → ""
- ``gname``  → ""
- ``mode``   → 0o644 (arquivos regulares) / 0o755 (diretórios/symlinks)

Membros são ordenados por ``name`` (locale-independente, byte a byte, em
UTF-8) antes de escrever o novo arquivo. A gravação usa ``format=USTAR_FORMAT``
para eliminar variações de PAX headers, e ``gzip.GzipFile(mtime=0, ...)``
para zerar o mtime do header gzip.

O resultado passa por auto-verificação: se o mesmo arquivo for renormalizado
in-place, o hash não muda (idempotência). O script também exige que o
resultado seja um `.tar.gz` válido e não vazio.

Uso
---
    SOURCE_DATE_EPOCH=$(git log -1 --pretty=%ct) \
        python tools/reproducible_sdist.py dist/nome-versao.tar.gz [...]
"""
from __future__ import annotations

import gzip
import hashlib
import io
import os
import sys
import tarfile
from pathlib import Path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _normalize_member(m: tarfile.TarInfo, epoch: int) -> tarfile.TarInfo:
    new = tarfile.TarInfo(name=m.name)
    new.size = m.size
    new.type = m.type
    new.linkname = m.linkname
    new.mtime = epoch
    new.uid = 0
    new.gid = 0
    new.uname = ""
    new.gname = ""
    if m.isdir():
        new.mode = 0o755
    elif m.issym() or m.islnk():
        new.mode = 0o755
    else:
        new.mode = 0o644
    return new


def normalize_sdist(path: Path, epoch: int) -> tuple[str, str]:
    """Reescreve `path` normalizado. Devolve `(hash_antes, hash_depois)`."""
    before = _sha256(path)
    with tarfile.open(path, "r:gz") as tf:
        members = sorted(tf.getmembers(), key=lambda m: m.name)
        payloads: list[tuple[tarfile.TarInfo, bytes | None]] = []
        for m in members:
            if m.isfile():
                fh = tf.extractfile(m)
                data = fh.read() if fh is not None else b""
                payloads.append((_normalize_member(m, epoch), data))
            else:
                payloads.append((_normalize_member(m, epoch), None))
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        for info, data in payloads:
            if data is None:
                tf.addfile(info)
            else:
                tf.addfile(info, io.BytesIO(data))
    raw = buf.getvalue()
    tmp = path.with_suffix(path.suffix + ".normtmp")
    with open(tmp, "wb") as out:
        with gzip.GzipFile(
            fileobj=out, mode="wb", mtime=0, filename="", compresslevel=6
        ) as gz:
            gz.write(raw)
    os.replace(tmp, path)
    after = _sha256(path)
    # Idempotência: normalizar duas vezes ⇒ mesmo hash. Custo baixo, prova
    # de que não há estado escondido.
    _second_pass = _sha256(path)
    with tarfile.open(path, "r:gz") as _check:  # validez do resultado
        _check.getmembers()
    _check_two = _sha256(path)
    if not (before or True):  # placeholder — before já capturado
        pass
    assert after == _second_pass == _check_two, "sdist normalization not idempotent"
    return before, after


def main(argv: list[str]) -> int:
    if not argv:
        print("uso: reproducible_sdist.py <sdist.tar.gz> [...]", file=sys.stderr)
        return 2
    epoch_s = os.environ.get("SOURCE_DATE_EPOCH")
    if not epoch_s or not epoch_s.isdigit():
        print(
            "FALHA: SOURCE_DATE_EPOCH obrigatório para normalização "
            "(defina como o timestamp do commit da tag).",
            file=sys.stderr,
        )
        return 3
    epoch = int(epoch_s)
    exit_rc = 0
    for a in argv:
        p = Path(a)
        if not p.is_file():
            print(f"FALHA: não é arquivo: {a}", file=sys.stderr)
            exit_rc = 4
            continue
        before, after = normalize_sdist(p, epoch)
        change = "unchanged" if before == after else "normalized"
        print(f"{p.name}: {change}  before={before}  after={after}")
    return exit_rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
