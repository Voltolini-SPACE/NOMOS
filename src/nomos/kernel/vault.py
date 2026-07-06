"""NOMOS kernel.vault — cofre local criptografado para chaves e segredos (v2).

Garantias:
- segredos nunca gravados em claro;
- KDF padrão Argon2id (t=3, m=64MiB, p=4); PBKDF2-SHA256/600k como fallback
  explícito apenas quando a lib argon2 não existe no host (campo `kdf` regista);
- cofres v1 (PBKDF2) são MIGRADOS para Argon2id no primeiro unlock bem-sucedido;
- downgrade é recusado fail-closed: cofre argon2id + lib ausente => VaultError;
- passphrase incorreta falha fechado (VaultLocked) e conta para o bloqueio
  progressivo: 3 falhas livres, depois espera exponencial 2s..900s persistida;
  estado de bloqueio corrompido = trava máxima (autorrecuperável no sucesso);
- arquivo 0600; escrita atômica; rotação re-encripta todas as entradas.
"""
from __future__ import annotations

from nomos.kernel.plataforma import chmod_privado

import base64
import json
import secrets
import time
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

try:  # opcional por host; ausência NUNCA degrada cofre argon2id existente
    from argon2.low_level import Type as _Argon2Type, hash_secret_raw as _argon2_raw
    _HAS_ARGON2 = True
except Exception:  # pragma: no cover - exercitado via monkeypatch nos testes
    _HAS_ARGON2 = False

KDF_PBKDF2 = "pbkdf2-sha256"
KDF_ARGON2ID = "argon2id"
KDF_ITERATIONS = 600_000          # pbkdf2 (compat v1)
ARGON2_TIME_COST = 3              # OWASP: t>=2/3
ARGON2_MEMORY_KIB = 64 * 1024     # 64 MiB
ARGON2_PARALLELISM = 4
MIN_PASSPHRASE = 10
FREE_FAILURES = 3                 # falhas sem espera
LOCK_BASE_S = 2                   # 4a falha: 2s; dobra a cada falha
LOCK_CAP_S = 900                  # teto 15 min
_CHECK_PLAINTEXT = b"NOMOS_VAULT_OK_v1"


class VaultError(Exception):
    pass


class VaultLocked(VaultError):
    """Passphrase incorreta ou cofre corrompido — falha fechado."""


class VaultLockedOut(VaultError):
    """Bloqueio progressivo ativo; tente novamente após `retry_in` segundos."""

    def __init__(self, retry_in: float):
        self.retry_in = max(0.0, retry_in)
        super().__init__(
            f"cofre bloqueado por tentativas falhas; aguarde {self.retry_in:.0f}s"
        )


def argon2_available() -> bool:
    return _HAS_ARGON2


def _derive_pbkdf2(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32, salt=salt, iterations=KDF_ITERATIONS
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def _derive_argon2id(passphrase: str, salt: bytes) -> bytes:
    raw = _argon2_raw(
        secret=passphrase.encode("utf-8"),
        salt=salt,
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_KIB,
        parallelism=ARGON2_PARALLELISM,
        hash_len=32,
        type=_Argon2Type.ID,
    )
    return base64.urlsafe_b64encode(raw)


def _derive(kdf: str, passphrase: str, salt: bytes) -> bytes:
    if kdf == KDF_ARGON2ID:
        if not argon2_available():
            raise VaultError(
                "cofre usa argon2id mas a lib argon2 não está disponível neste "
                "host; instale 'argon2-cffi' — downgrade é recusado (fail-closed)"
            )
        return _derive_argon2id(passphrase, salt)
    if kdf == KDF_PBKDF2:
        return _derive_pbkdf2(passphrase, salt)
    raise VaultError(f"kdf desconhecido no cofre: {kdf!r} (fail-closed)")


def _preferred_kdf() -> str:
    return KDF_ARGON2ID if argon2_available() else KDF_PBKDF2


class _Lockout:
    """Bloqueio progressivo persistido, com relógio injetável para teste."""

    def __init__(self, path: Path, clock=time.time):
        self.path = Path(path)
        self.clock = clock

    def _load(self) -> dict:
        if not self.path.exists():
            return {"failures": 0, "locked_until": 0.0}
        try:
            data = json.loads(self.path.read_text())
            return {
                "failures": int(data["failures"]),
                "locked_until": float(data["locked_until"]),
            }
        except Exception:
            # Estado corrompido: fail-closed => trava máxima, mas autorrecuperável
            # (um unlock correto após a espera limpa o estado).
            now = self.clock()
            state = {"failures": FREE_FAILURES + 10, "locked_until": now + LOCK_CAP_S}
            self._save(state)
            return state

    def _save(self, state: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state))
        chmod_privado(tmp, 0o600)
        tmp.replace(self.path)
        chmod_privado(self.path, 0o600)

    def check(self) -> None:
        state = self._load()
        remaining = state["locked_until"] - self.clock()
        if remaining > 0:
            raise VaultLockedOut(remaining)

    def register_failure(self) -> None:
        state = self._load()
        state["failures"] += 1
        extra = state["failures"] - FREE_FAILURES
        if extra > 0:
            delay = min(LOCK_BASE_S * (2 ** (extra - 1)), LOCK_CAP_S)
            state["locked_until"] = self.clock() + delay
        self._save(state)

    def reset(self) -> None:
        if self.path.exists():
            self._save({"failures": 0, "locked_until": 0.0})


class Vault:
    def __init__(self, path: Path, clock=time.time):
        self.path = Path(path)
        self._lockout = _Lockout(self.path.with_name(self.path.name + ".lockout"), clock)

    # ---------- ciclo de vida ----------
    def exists(self) -> bool:
        return self.path.exists()

    def init(self, passphrase: str) -> None:
        if self.exists():
            raise VaultError("cofre já existe; use rotate para trocar a passphrase")
        if len(passphrase) < MIN_PASSPHRASE:
            raise VaultError(f"passphrase deve ter no mínimo {MIN_PASSPHRASE} caracteres")
        kdf = _preferred_kdf()
        salt = secrets.token_bytes(16)
        f = Fernet(_derive(kdf, passphrase, salt))
        data = {
            "version": 2,
            "kdf": kdf,
            "iterations": KDF_ITERATIONS if kdf == KDF_PBKDF2 else None,
            "argon2": (
                {"t": ARGON2_TIME_COST, "m_kib": ARGON2_MEMORY_KIB, "p": ARGON2_PARALLELISM}
                if kdf == KDF_ARGON2ID
                else None
            ),
            "salt": base64.b64encode(salt).decode(),
            "check": f.encrypt(_CHECK_PLAINTEXT).decode(),
            "entries": {},
        }
        self._write(data)

    def _read(self) -> dict:
        if not self.exists():
            raise VaultError("cofre inexistente; execute 'nomos vault init'")
        return json.loads(self.path.read_text())

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        chmod_privado(tmp, 0o600)
        tmp.replace(self.path)
        chmod_privado(self.path, 0o600)

    # ---------- unlock com lockout + migração ----------
    def _unlock(self, passphrase: str) -> tuple[Fernet, dict]:
        """Valida passphrase sob bloqueio progressivo.

        Sucesso: zera o lockout e, se o cofre for v1/pbkdf2 e argon2 existir,
        MIGRA (re-encripta tudo com argon2id) antes de devolver o par.
        """
        self._lockout.check()
        data = self._read()
        kdf = data.get("kdf", KDF_PBKDF2)
        salt = base64.b64decode(data["salt"])
        f = Fernet(_derive(kdf, passphrase, salt))
        try:
            if f.decrypt(data["check"].encode()) != _CHECK_PLAINTEXT:
                raise InvalidToken
        except InvalidToken:
            self._lockout.register_failure()
            raise VaultLocked("passphrase incorreta") from None
        self._lockout.reset()
        if kdf == KDF_PBKDF2 and argon2_available():
            f, data = self._migrate_to_argon2(f, data, passphrase)
        return f, data

    def _migrate_to_argon2(self, old_f: Fernet, data: dict, passphrase: str):
        plain = {k: old_f.decrypt(v.encode()) for k, v in data["entries"].items()}
        salt = secrets.token_bytes(16)
        new_f = Fernet(_derive(KDF_ARGON2ID, passphrase, salt))
        data = dict(data)
        data["version"] = 2
        data["kdf"] = KDF_ARGON2ID
        data["iterations"] = None
        data["argon2"] = {
            "t": ARGON2_TIME_COST, "m_kib": ARGON2_MEMORY_KIB, "p": ARGON2_PARALLELISM
        }
        data["salt"] = base64.b64encode(salt).decode()
        data["check"] = new_f.encrypt(_CHECK_PLAINTEXT).decode()
        data["entries"] = {k: new_f.encrypt(v).decode() for k, v in plain.items()}
        self._write(data)
        return new_f, data

    # ---------- operações ----------
    def verify_passphrase(self, passphrase: str) -> None:
        """Valida a passphrase (sob o mesmo bloqueio progressivo) sem ler nem
        gravar entrada nenhuma — para fluxos que precisam confirmar a senha
        ANTES de consumir material sensível (ex.: absorver arquivo de chave).
        Levanta VaultLocked/VaultLockedOut em falha; silêncio = ok."""
        self._unlock(passphrase)

    def set(self, name: str, secret: str, passphrase: str) -> None:
        f, data = self._unlock(passphrase)
        data["entries"][name] = f.encrypt(secret.encode("utf-8")).decode()
        self._write(data)

    def get(self, name: str, passphrase: str) -> str:
        f, data = self._unlock(passphrase)
        token = data["entries"].get(name)
        if token is None:
            raise VaultError(f"entrada inexistente: {name}")
        return f.decrypt(token.encode()).decode("utf-8")

    def names(self) -> list[str]:
        """Somente os NOMES das entradas (metadado); nunca os valores."""
        if not self.exists():
            return []
        return sorted(self._read()["entries"].keys())

    def kdf(self) -> str:
        return self._read().get("kdf", KDF_PBKDF2)

    def delete(self, name: str, passphrase: str) -> None:
        f, data = self._unlock(passphrase)
        if name not in data["entries"]:
            raise VaultError(f"entrada inexistente: {name}")
        del data["entries"][name]
        self._write(data)

    def rotate(self, old_passphrase: str, new_passphrase: str) -> int:
        if len(new_passphrase) < MIN_PASSPHRASE:
            raise VaultError(f"passphrase deve ter no mínimo {MIN_PASSPHRASE} caracteres")
        old_f, data = self._unlock(old_passphrase)
        plain = {k: old_f.decrypt(v.encode()) for k, v in data["entries"].items()}
        kdf = _preferred_kdf()
        new_salt = secrets.token_bytes(16)
        new_f = Fernet(_derive(kdf, new_passphrase, new_salt))
        data["kdf"] = kdf
        data["salt"] = base64.b64encode(new_salt).decode()
        data["check"] = new_f.encrypt(_CHECK_PLAINTEXT).decode()
        data["entries"] = {k: new_f.encrypt(v).decode() for k, v in plain.items()}
        self._write(data)
        return len(plain)
