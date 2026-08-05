"""Regressões unitárias para `tools/reproducible_sdist.py`.

Cobre o contrato descrito em H4.9:

1. Idempotência: normalizar duas vezes ⇒ mesmo hash.
2. Determinismo: dois `.tar.gz` DIFERENTES construídos do mesmo conteúdo
   (com mtimes e ordem distintas) convergem para o MESMO hash depois de
   normalizados.
3. Preservação de conteúdo: nomes de membros, bytes de cada arquivo e a
   distinção arquivo/diretório sobrevivem à normalização.
4. Metadados normalizados: mtime = SOURCE_DATE_EPOCH; uid=0, gid=0,
   uname="", gname=""; mode 0o644 (arquivos) / 0o755 (diretórios).
5. Falha explícita quando SOURCE_DATE_EPOCH ausente ou inválido.

Não depende de rede nem de dependências externas — só stdlib.
"""
from __future__ import annotations

import hashlib
import io
import os
import subprocess
import sys
import tarfile
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "tools" / "reproducible_sdist.py"


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _make_sdist(path: Path, entries: list[tuple[str, bytes | None, int]]) -> None:
    """Escreve um `.tar.gz` mínimo. Cada entry = (name, bytes_or_None, mtime).

    `None` como bytes ⇒ diretório. Ordem preservada exatamente como recebida.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, data, mtime in entries:
            info = tarfile.TarInfo(name=name)
            info.mtime = mtime
            info.uid = 1234
            info.gid = 5678
            info.uname = "somebody"
            info.gname = "somegroup"
            if data is None:
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                tf.addfile(info)
            else:
                info.size = len(data)
                info.mode = 0o600
                tf.addfile(info, io.BytesIO(data))
    import gzip
    with open(path, "wb") as out:
        with gzip.GzipFile(fileobj=out, mode="wb", mtime=mtime, filename="orig") as gz:
            gz.write(buf.getvalue())


def _run(argv: list[str], epoch: str | None) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ.get("PATH", "")}
    if epoch is not None:
        env["SOURCE_DATE_EPOCH"] = epoch
    return subprocess.run(
        [sys.executable, str(TOOL), *argv],
        env=env,
        capture_output=True,
        text=True,
    )


def test_normalizacao_idempotente(tmp_path: Path) -> None:
    p = tmp_path / "s.tar.gz"
    _make_sdist(p, [
        ("proj/", None, 1_000),
        ("proj/a.txt", b"conteudo A", 1_000),
        ("proj/sub/", None, 2_000),
        ("proj/sub/b.txt", b"conteudo B\n", 3_000),
    ])
    r1 = _run([str(p)], epoch="1785875362")
    assert r1.returncode == 0, r1.stderr
    h1 = _sha256(p)
    r2 = _run([str(p)], epoch="1785875362")
    assert r2.returncode == 0, r2.stderr
    h2 = _sha256(p)
    assert h1 == h2, f"normalizacao nao idempotente: {h1} != {h2}"


def test_convergencia_de_hashes(tmp_path: Path) -> None:
    """Dois sdists com mesmos NOMES+BYTES mas mtimes/ordem/uid diferentes
    convergem para hash idêntico após normalização."""
    p1 = tmp_path / "a.tar.gz"
    p2 = tmp_path / "b.tar.gz"
    # p1: ordem alfabética direta, mtimes 1
    _make_sdist(p1, [
        ("proj/", None, 1_000),
        ("proj/one.txt", b"1", 1_000),
        ("proj/two.txt", b"2", 1_000),
    ])
    # p2: ordem invertida, mtimes wall-clock-like
    _make_sdist(p2, [
        ("proj/two.txt", b"2", 9_000_000),
        ("proj/one.txt", b"1", 9_000_001),
        ("proj/", None, 9_000_002),
    ])
    assert _sha256(p1) != _sha256(p2)
    _run([str(p1)], epoch="1785875362")
    _run([str(p2)], epoch="1785875362")
    assert _sha256(p1) == _sha256(p2), "sdists deveriam convergir apos normalizacao"


def test_conteudo_preservado(tmp_path: Path) -> None:
    p = tmp_path / "s.tar.gz"
    payload_a = b"linha 1\nlinha 2\n"
    payload_b = os.urandom(4096)  # bytes arbitrários
    _make_sdist(p, [
        ("proj/", None, 1_000),
        ("proj/a.txt", payload_a, 1_000),
        ("proj/b.bin", payload_b, 1_000),
        ("proj/d/", None, 1_000),
    ])
    _run([str(p)], epoch="1785875362")
    with tarfile.open(p, "r:gz") as tf:
        # `tarfile` normaliza nomes de diretório removendo a barra final —
        # comparamos sem `/`. A distinção arquivo/diretório vem do type do
        # membro, não do sufixo do nome.
        by_name = {m.name.rstrip("/"): m for m in tf.getmembers()}
        assert sorted(by_name) == ["proj", "proj/a.txt", "proj/b.bin", "proj/d"]
        assert tf.extractfile(by_name["proj/a.txt"]).read() == payload_a
        assert tf.extractfile(by_name["proj/b.bin"]).read() == payload_b
        assert by_name["proj"].isdir()
        assert by_name["proj/d"].isdir()
        assert by_name["proj/a.txt"].isfile()


def test_metadata_zerados(tmp_path: Path) -> None:
    p = tmp_path / "s.tar.gz"
    _make_sdist(p, [
        ("proj/", None, 5_000),
        ("proj/f.txt", b"x", 5_000),
    ])
    EPOCH = "1785875362"
    _run([str(p)], epoch=EPOCH)
    with tarfile.open(p, "r:gz") as tf:
        for m in tf.getmembers():
            assert int(m.mtime) == int(EPOCH), f"mtime nao zerado em {m.name}"
            assert m.uid == 0 and m.gid == 0
            assert m.uname == "" and m.gname == ""
            if m.isdir():
                assert m.mode == 0o755
            elif m.isfile():
                assert m.mode == 0o644


def test_falha_sem_epoch(tmp_path: Path) -> None:
    p = tmp_path / "s.tar.gz"
    _make_sdist(p, [("proj/", None, 1_000), ("proj/x.txt", b"x", 1_000)])
    r = _run([str(p)], epoch=None)
    assert r.returncode != 0
    assert "SOURCE_DATE_EPOCH" in r.stderr


def test_falha_epoch_invalido(tmp_path: Path) -> None:
    p = tmp_path / "s.tar.gz"
    _make_sdist(p, [("proj/", None, 1_000), ("proj/x.txt", b"x", 1_000)])
    r = _run([str(p)], epoch="nao-numerico")
    assert r.returncode != 0


# ============================================================
# Testes adversariais — fail-closed conforme H4.10 §4.1
# ============================================================


def _make_hostile_sdist(
    path: Path,
    entries: list[tuple[str, bytes | None, int, str | None]],
) -> None:
    """Como `_make_sdist`, mas aceita 4-tupla (name, data, mtime, linkname).

    `data=None` + `linkname=None` ⇒ diretório.
    `data=None` + `linkname="..."` ⇒ symlink.
    Bytes ⇒ arquivo com esse conteúdo.
    """
    import gzip as _gz
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, data, mtime, linkname in entries:
            info = tarfile.TarInfo(name=name)
            info.mtime = mtime
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            if linkname is not None:
                info.type = tarfile.SYMTYPE
                info.linkname = linkname
                info.mode = 0o777
                tf.addfile(info)
            elif data is None:
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                tf.addfile(info)
            else:
                info.size = len(data)
                info.mode = 0o644
                tf.addfile(info, io.BytesIO(data))
    with open(path, "wb") as out:
        with _gz.GzipFile(fileobj=out, mode="wb", mtime=0) as gz:
            gz.write(buf.getvalue())


def test_rejeita_path_traversal(tmp_path: Path) -> None:
    p = tmp_path / "s.tar.gz"
    _make_hostile_sdist(p, [
        ("proj/", None, 1_000, None),
        ("proj/../escape.txt", b"malicioso", 1_000, None),
    ])
    r = _run([str(p)], epoch="1785875362")
    assert r.returncode != 0
    assert "traversal" in r.stderr.lower() or "traversal" in r.stdout.lower()


def test_rejeita_caminho_absoluto(tmp_path: Path) -> None:
    p = tmp_path / "s.tar.gz"
    _make_hostile_sdist(p, [
        ("proj/", None, 1_000, None),
        ("/etc/passwd", b"root:x:0:0", 1_000, None),
    ])
    r = _run([str(p)], epoch="1785875362")
    assert r.returncode != 0
    assert "absoluto" in r.stderr.lower() or "absoluto" in r.stdout.lower()


def test_rejeita_symlink_absoluto(tmp_path: Path) -> None:
    p = tmp_path / "s.tar.gz"
    _make_hostile_sdist(p, [
        ("proj/", None, 1_000, None),
        ("proj/evil", None, 1_000, "/etc/passwd"),
    ])
    r = _run([str(p)], epoch="1785875362")
    assert r.returncode != 0


def test_rejeita_symlink_traversal(tmp_path: Path) -> None:
    p = tmp_path / "s.tar.gz"
    _make_hostile_sdist(p, [
        ("proj/", None, 1_000, None),
        ("proj/evil", None, 1_000, "../../../etc/passwd"),
    ])
    r = _run([str(p)], epoch="1785875362")
    assert r.returncode != 0


def test_rejeita_nome_gigante_ustar(tmp_path: Path) -> None:
    p = tmp_path / "s.tar.gz"
    # PAX pode escrever nomes gigantes; USTAR de saída não.
    huge = "a" * 300
    _make_hostile_sdist(p, [
        ("proj/", None, 1_000, None),
        (f"proj/{huge}.txt", b"x", 1_000, None),
    ])
    r = _run([str(p)], epoch="1785875362")
    assert r.returncode != 0


def test_rejeita_dispositivo_especial(tmp_path: Path) -> None:
    """CHRTYPE/BLKTYPE/FIFOTYPE não devem existir em sdist."""
    import gzip as _gz
    p = tmp_path / "s.tar.gz"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        d = tarfile.TarInfo(name="proj/")
        d.type = tarfile.DIRTYPE
        d.mode = 0o755
        tf.addfile(d)
        fifo = tarfile.TarInfo(name="proj/pipe")
        fifo.type = tarfile.FIFOTYPE
        fifo.mode = 0o600
        tf.addfile(fifo)
    with open(p, "wb") as out:
        with _gz.GzipFile(fileobj=out, mode="wb", mtime=0) as gz:
            gz.write(buf.getvalue())
    r = _run([str(p)], epoch="1785875362")
    assert r.returncode != 0
    assert "não suportado" in r.stderr or "not supported" in r.stderr.lower() \
        or "nao suportado" in r.stderr.lower() or "type" in r.stderr.lower()


def test_rejeita_membros_duplicados(tmp_path: Path) -> None:
    """Dois membros com nome idêntico após ordenação."""
    p = tmp_path / "s.tar.gz"
    _make_hostile_sdist(p, [
        ("proj/", None, 1_000, None),
        ("proj/x.txt", b"primeiro", 1_000, None),
        ("proj/x.txt", b"segundo", 1_000, None),
    ])
    r = _run([str(p)], epoch="1785875362")
    assert r.returncode != 0
    assert "duplicado" in r.stderr.lower() or "duplicad" in r.stderr.lower()


def test_rejeita_arquivo_truncado(tmp_path: Path) -> None:
    """gzip corrompido / tar incompleto ⇒ falha explícita."""
    p = tmp_path / "s.tar.gz"
    # Bytes aleatórios sem cabeçalho gzip válido
    p.write_bytes(b"\x1f\x8b\x08\x00" + b"\x00" * 12 + b"lixo")
    r = _run([str(p)], epoch="1785875362")
    assert r.returncode != 0
