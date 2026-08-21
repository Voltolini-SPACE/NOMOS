"""NOMOS adapters.monitor — hash de alvo para monitor-mode (NH-018c).

Supressão por CONTEÚDO, nunca por mtime/size — "mtime mente" é landmine
documentada da casa (touch sem mudança não pode disparar; mudança com
mtime preservado não pode passar). Alvo ausente vira a sentinela
`AUSENTE`: aparecer e sumir SÃO mudanças.
"""
from __future__ import annotations

import hashlib
import os
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

    **Symlink NUNCA é seguido** (achado da revisão adversarial): o PDP
    confere `monitorar_alvo` na CRIAÇÃO, mas qualquer processo com escrita
    na raiz autorizada poderia plantar depois um link para fora e
    transformar o ticker num leitor — e num oráculo de mudança — de
    qualquer arquivo legível do sistema, sem PDP e sem trilha. Um link é
    hasheado pelo seu ALVO TEXTUAL (o destino aponta para onde? mudou?),
    nunca pelo conteúdo apontado.
    """
    p = Path(caminho)
    if p.is_symlink():
        # o próprio alvo monitorado ser um link já é recusa: o escopo foi
        # conferido para um caminho, não para o que ele apontar amanhã
        raise ErroInvalido(
            f"alvo monitorado é um symlink ({p}) — recusado: o escopo do "
            "PDP vale para o caminho conferido, não para o destino que o "
            "link tiver depois")
    if not p.exists():
        return SENTINELA_AUSENTE
    if p.is_file():
        return _sha_arquivo(p)
    if not p.is_dir():
        return SENTINELA_AUSENTE          # socket/fifo: trata como ausente
    h = hashlib.sha256()
    entradas = sorted(p.rglob("*"))
    arquivos = [x for x in entradas if x.is_symlink() or x.is_file()]
    if len(arquivos) > MONITOR_ARQUIVOS_MAX:
        raise ErroInvalido(
            f"alvo monitorado tem {len(arquivos)} arquivos "
            f"(teto {MONITOR_ARQUIVOS_MAX}) — recusado na criação: hashear "
            "isso a cada tick custaria o que o teto existe para evitar")
    for arq in arquivos:
        h.update(str(arq.relative_to(p)).encode())
        h.update(b"\0")
        if arq.is_symlink():
            # conteúdo do LINK (para onde aponta), nunca do destino
            h.update(b"symlink:")
            h.update(os.readlink(arq).encode())
        else:
            h.update(_sha_arquivo(arq).encode())
        h.update(b"\0")
    return h.hexdigest()
