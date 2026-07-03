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
    """Exporta TODAS as memórias cifradas. Devolve a quantidade exportada."""
    itens = [{"ts": i.ts, "role": i.role, "text": i.text}
             for i in mem.recent(n=1_000_000)]
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
    novas = ignoradas = 0
    for item in dados.get("itens", []):
        chave = (item.get("role", "note"), item.get("text", ""))
        if chave in existentes or not chave[1]:
            ignoradas += 1
            continue
        mem.remember(chave[0], chave[1])
        novas += 1
    return novas, ignoradas
