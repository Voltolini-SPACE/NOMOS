"""NOMOS simple.backup_total — o NOMOS inteiro num arquivo cifrado (v1.0.1).

Empacota o NOMOS_HOME (perfil, memórias, cofre, política, trilha, rotinas,
skills, feedback, trust) em tar → Fernet (AES+HMAC) com chave PBKDF2-SHA256
600k. Exclui por padrão o que é re-baixável/efêmero: `modelos/` (GBs) e
`sandbox/` — sempre avisando.

Restaurar é conservador por lei:
- home de destino NÃO-vazio => só com confirmação explícita do chamador;
- o conteúdo atual é movido para `.antes-restauro-<ts>/` ANTES de restaurar —
  errou? volta;
- senha errada/arquivo adulterado => nada acontece (Fernet autentica);
- caminhos do tar são validados (nada de escapar do home via ../).
"""
from __future__ import annotations

import base64
import hashlib
import io
import os
import tarfile
import time
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from nomos.kernel.plataforma import chmod_privado

ITERACOES = 600_000
MAGICO = b"NOMOS-BACKUP-TOTAL-v1\n"
EXCLUIR_PADRAO = ("modelos", "sandbox", "backups")


class BackupTotalError(Exception):
    pass


def _chave(senha: str, sal: bytes) -> bytes:
    if len(senha or "") < 8:
        raise BackupTotalError("senha do backup precisa ter pelo menos 8 caracteres")
    kdf = hashlib.pbkdf2_hmac("sha256", senha.encode(), sal, ITERACOES, dklen=32)
    return base64.urlsafe_b64encode(kdf)


def criar(home: Path, destino: Path, senha: str,
          excluir: tuple = EXCLUIR_PADRAO) -> tuple[int, list[str]]:
    """Cria o backup cifrado. Devolve (arquivos_incluidos, pastas_excluidas)."""
    home = Path(home)
    if not home.is_dir():
        raise BackupTotalError(f"NOMOS home não encontrado: {home}")
    destino = Path(destino)
    if destino.exists():
        raise BackupTotalError(f"já existe um arquivo em {destino} — "
                               "não sobrescrevo backup (escolha outro nome)")
    buf = io.BytesIO()
    incluidos = 0
    excluidas: list[str] = []
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for item in sorted(home.rglob("*")):
            rel = item.relative_to(home)
            if rel.parts and rel.parts[0] in excluir:
                if len(rel.parts) == 1 and item.is_dir():
                    excluidas.append(rel.parts[0] + "/")
                continue
            if item.is_file():
                tar.add(item, arcname=str(rel))
                incluidos += 1
    sal = os.urandom(16)
    blob = Fernet(_chave(senha, sal)).encrypt(buf.getvalue())
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(MAGICO + base64.b64encode(sal) + b"\n" + blob)
    chmod_privado(destino, 0o600)
    return incluidos, excluidas


def inspecionar(origem: Path, senha: str) -> list[str]:
    """Lista o conteúdo do backup sem restaurar nada."""
    dados = _decifrar(origem, senha)
    with tarfile.open(fileobj=io.BytesIO(dados), mode="r:gz") as tar:
        return sorted(m.name for m in tar.getmembers() if m.isfile())


def _decifrar(origem: Path, senha: str) -> bytes:
    origem = Path(origem)
    if not origem.exists():
        raise BackupTotalError(f"backup não encontrado: {origem}")
    bruto = origem.read_bytes()
    if not bruto.startswith(MAGICO):
        raise BackupTotalError("este arquivo não é um backup total do NOMOS")
    resto = bruto[len(MAGICO):]
    try:
        linha_sal, blob = resto.split(b"\n", 1)
        sal = base64.b64decode(linha_sal)
    except Exception:
        raise BackupTotalError("arquivo de backup malformado") from None
    try:
        return Fernet(_chave(senha, sal)).decrypt(blob)
    except InvalidToken:
        raise BackupTotalError("senha incorreta ou backup adulterado — "
                               "nada foi restaurado") from None


def restaurar(home: Path, origem: Path, senha: str,
              permitir_sobrescrever: bool = False) -> tuple[int, str]:
    """Restaura o backup no home. Devolve (arquivos_restaurados, guardado_em).

    Se o home tiver conteúdo, exige permitir_sobrescrever=True (o chamador é
    quem coleta a confirmação humana) e move o atual para .antes-restauro-<ts>.
    """
    home = Path(home)
    dados = _decifrar(origem, senha)   # falha ANTES de tocar em qualquer coisa

    guardado_em = ""
    conteudo_atual = [p for p in home.iterdir()] if home.is_dir() else []
    if conteudo_atual:
        if not permitir_sobrescrever:
            raise BackupTotalError(
                "o NOMOS home atual não está vazio — restauro exige "
                "confirmação explícita (nada foi alterado)")
        abrigo = home.parent / f".antes-restauro-{int(time.time())}"
        abrigo.mkdir(parents=True)
        for p in conteudo_atual:
            p.rename(abrigo / p.name)
        guardado_em = str(abrigo)

    home.mkdir(parents=True, exist_ok=True)
    chmod_privado(home, 0o700)
    restaurados = 0
    with tarfile.open(fileobj=io.BytesIO(dados), mode="r:gz") as tar:
        for m in tar.getmembers():
            alvo = (home / m.name).resolve()
            if not str(alvo).startswith(str(home.resolve())):
                raise BackupTotalError(f"caminho suspeito no backup: {m.name}")
            if m.isfile():
                alvo.parent.mkdir(parents=True, exist_ok=True)
                fh = tar.extractfile(m)
                alvo.write_bytes(fh.read() if fh else b"")
                chmod_privado(alvo, 0o600)
                restaurados += 1
    return restaurados, guardado_em
