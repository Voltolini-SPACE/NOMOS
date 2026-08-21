"""NOMOS adapters.monitor — hash de alvo para monitor-mode (NH-018c).

Supressão por CONTEÚDO, nunca por mtime/size — "mtime mente" é landmine
documentada da casa (touch sem mudança não pode disparar; mudança com
mtime preservado não pode passar). Alvo ausente vira a sentinela
`AUSENTE`: aparecer e sumir SÃO mudanças.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from nomos.adapters.contrato import ErroInvalido

SENTINELA_AUSENTE = "AUSENTE"
MONITOR_ARQUIVOS_MAX = 10_000
_BLOCO = 64 * 1024


def _sha_arquivo(caminho: Path) -> str:
    h = hashlib.sha256()
    with caminho.open("rb") as fh:
        while True:
            bloco = fh.read(_BLOCO)
            if not bloco:
                break
            h.update(bloco)
    return h.hexdigest()


def hash_alvo(caminho: str | Path) -> str:
    """SHA-256 do CONTEÚDO do alvo (arquivo ou árvore de diretório).

    Diretório: lista ordenada de (caminho relativo, sha do conteúdo) —
    determinístico, independente de ordem de listagem e de mtime. Acima de
    `MONITOR_ARQUIVOS_MAX` arquivos ⇒ `ErroInvalido` (recusa explícita,
    nunca degradação silenciosa).
    """
    p = Path(caminho)
    if not p.exists():
        return SENTINELA_AUSENTE
    if p.is_file():
        return _sha_arquivo(p)
    if not p.is_dir():
        return SENTINELA_AUSENTE          # socket/fifo: trata como ausente
    h = hashlib.sha256()
    arquivos = sorted(x for x in p.rglob("*") if x.is_file())
    if len(arquivos) > MONITOR_ARQUIVOS_MAX:
        raise ErroInvalido(
            f"alvo monitorado tem {len(arquivos)} arquivos "
            f"(teto {MONITOR_ARQUIVOS_MAX}) — recusado na criação: hashear "
            "isso a cada tick custaria o que o teto existe para evitar")
    for arq in arquivos:
        h.update(str(arq.relative_to(p)).encode())
        h.update(b"\0")
        h.update(_sha_arquivo(arq).encode())
        h.update(b"\0")
    return h.hexdigest()
