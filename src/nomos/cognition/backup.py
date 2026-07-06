"""NOMOS cognition.backup — exportar/importar memórias, cifrado de ponta a ponta.

Formato: JSON → Fernet (AES-128-CBC + HMAC) com chave derivada por PBKDF2-SHA256
(600k iterações, sal aleatório por arquivo). O arquivo exportado é inútil sem a
senha. Nada disso passa pela rede; é um arquivo local que VOCÊ leva para onde
quiser. Importar nunca apaga o que já existe (só adiciona, deduplicando).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from nomos.kernel.plataforma import chmod_privado

ITERACOES = 600_000
MAGICO = "NOMOS-MEMORIAS-v1"


class BackupError(Exception):
    pass


def _chave(senha: str, sal: bytes) -> bytes:
    if len(senha or "") < 8:
        raise BackupError("senha do backup precisa ter pelo menos 8 caracteres")
    kdf = hashlib.pbkdf2_hmac("sha256", senha.encode(), sal, ITERACOES, dklen=32)
    return base64.urlsafe_b64encode(kdf)


def exportar(mem, destino: Path, senha: str) -> int:
    """Exporta TODAS as memórias cifradas. Devolve a quantidade exportada.

    Fiel ao F4: preserva ts e os metadados tipados (tipo/fonte/confianca) —
    sem eles o ciclo exportar→importar degradava a memória silenciosamente.
    """
    rows = mem.conn.execute(
        "SELECT ts, role, text, tipo, fonte, confianca FROM memories "
        "ORDER BY id").fetchall()
    itens = [{"ts": r[0], "role": r[1], "text": r[2],
              "tipo": r[3] or "", "fonte": r[4] or "",
              "confianca": r[5] if r[5] is not None else 1.0}
             for r in rows]
    sal = os.urandom(16)
    corpo = json.dumps({"formato": MAGICO, "itens": itens},
                       ensure_ascii=False).encode()
    blob = Fernet(_chave(senha, sal)).encrypt(corpo)
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(base64.b64encode(sal) + b"\n" + blob)
    chmod_privado(destino, 0o600)
    return len(itens)


def importar(mem, origem: Path, senha: str) -> tuple[int, int]:
    """Importa memórias de um backup. Devolve (novas, ignoradas_duplicadas)."""
    origem = Path(origem)
    if not origem.exists():
        raise BackupError(f"backup não encontrado: {origem}")
    try:
        linha_sal, blob = origem.read_bytes().split(b"\n", 1)
        sal = base64.b64decode(linha_sal)
    except Exception:
        raise BackupError("arquivo de backup malformado") from None
    try:
        corpo = Fernet(_chave(senha, sal)).decrypt(blob)
    except InvalidToken:
        raise BackupError("senha incorreta ou backup corrompido — nada importado") \
            from None
    dados = json.loads(corpo)
    if dados.get("formato") != MAGICO:
        raise BackupError("este arquivo não é um backup de memórias do NOMOS")
    existentes = {(i.role, i.text) for i in mem.recent(n=1_000_000)}
    roles_ok = {"user", "assistant", "system", "note"}
    novas = ignoradas = 0
    for item in dados.get("itens", []):
        role = item.get("role", "note")
        if role not in roles_ok:
            role = "note"
        chave = (role, item.get("text", ""))
        if chave in existentes or not chave[1]:
            ignoradas += 1
            continue
        # restaura ts e metadados tipados (backups v1 antigos: defaults seguros)
        try:
            ts = float(item.get("ts") or time.time())
        except (TypeError, ValueError):
            ts = time.time()
        try:
            conf = float(item.get("confianca", 1.0))
        except (TypeError, ValueError):
            conf = 1.0
        mem.conn.execute(
            "INSERT INTO memories(ts, role, text, tipo, fonte, confianca) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ts, role, chave[1], str(item.get("tipo") or ""),
             str(item.get("fonte") or ""), conf))
        existentes.add(chave)
        novas += 1
    mem.conn.commit()
    return novas, ignoradas
