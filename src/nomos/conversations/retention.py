"""NOMOS conversations.retention — retenção configurável + export cifrado (F2).

Retenção: apaga conversas mais velhas que N dias (config no perfil; padrão:
guardar para sempre, 0 = sem expiração). Nunca envia nada para fora — só apaga
localmente, com aviso de quantas.

Export/import: mesma stack do backup (Fernet + PBKDF2 600k), arquivo 0600.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from nomos.conversations.store import ConversationStore
from nomos.kernel.plataforma import chmod_privado

ITERACOES = 600_000
MAGICO = b"NOMOS-CONVERSAS-v1\n"
CAMPO_RETENCAO = "conversas_retencao_dias"   # perfil; 0 = sem expiração


class ConversaBackupError(Exception):
    pass


def dias_retencao(perfil: dict | None = None) -> int:
    from nomos.kernel import config
    perfil = perfil if perfil is not None else (config.load_agent() or {})
    try:
        return max(0, int(perfil.get(CAMPO_RETENCAO, 0)))
    except (TypeError, ValueError):
        return 0


def aplicar_retencao(store: ConversationStore, dias: int) -> int:
    """Apaga conversas NÃO fixadas mais velhas que `dias`. Devolve quantas."""
    if dias <= 0:
        return 0
    limite = time.time() - dias * 86400
    apagadas = 0
    for c in store.listar(limite=100000):
        if not c.fixada and c.ultima_ts and c.ultima_ts < limite:
            if store.esquecer(c.id):
                apagadas += 1
    return apagadas


def _chave(senha: str, sal: bytes) -> bytes:
    if len(senha or "") < 8:
        raise ConversaBackupError("senha precisa ter pelo menos 8 caracteres")
    kdf = hashlib.pbkdf2_hmac("sha256", senha.encode(), sal, ITERACOES, dklen=32)
    return base64.urlsafe_b64encode(kdf)


def exportar(store: ConversationStore, destino: Path, senha: str) -> int:
    itens = store.exportar_itens()
    sal = os.urandom(16)
    corpo = json.dumps({"formato": MAGICO.decode().strip(), "itens": itens},
                       ensure_ascii=False).encode()
    blob = Fernet(_chave(senha, sal)).encrypt(corpo)
    destino = Path(destino)
    if destino.exists():
        raise ConversaBackupError(f"já existe {destino} — escolha outro nome")
    destino.write_bytes(MAGICO + base64.b64encode(sal) + b"\n" + blob)
    chmod_privado(destino, 0o600)
    return len(itens)


def importar(store: ConversationStore, origem: Path, senha: str) -> int:
    origem = Path(origem)
    if not origem.exists():
        raise ConversaBackupError(f"arquivo não encontrado: {origem}")
    bruto = origem.read_bytes()
    if not bruto.startswith(MAGICO):
        raise ConversaBackupError("este arquivo não é um export de conversas do NOMOS")
    try:
        linha_sal, blob = bruto[len(MAGICO):].split(b"\n", 1)
        sal = base64.b64decode(linha_sal)
    except Exception:
        raise ConversaBackupError("arquivo malformado") from None
    try:
        corpo = Fernet(_chave(senha, sal)).decrypt(blob)
    except InvalidToken:
        raise ConversaBackupError("senha incorreta ou arquivo adulterado — "
                                  "nada importado") from None
    return store.importar_itens(json.loads(corpo).get("itens", []))
