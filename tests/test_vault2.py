"""C2 — cofre v2: Argon2id, migração, downgrade fail-closed, lockout progressivo."""
import json

import pytest

from nomos.kernel import vault as vmod
from nomos.kernel.vault import (
    KDF_ARGON2ID, KDF_PBKDF2, LOCK_CAP_S, Vault, VaultError, VaultLocked, VaultLockedOut,
)

PASS = "correta-e-longa-123"


class FakeClock:
    def __init__(self):
        self.t = 1_000.0
    def __call__(self):
        return self.t
    def advance(self, s):
        self.t += s


@pytest.fixture()
def clock():
    return FakeClock()


@pytest.fixture()
def vault(tmp_path, clock):
    v = Vault(tmp_path / "vault.json", clock=clock)
    v.init(PASS)
    return v


def test_new_vault_uses_argon2id(vault):
    assert vmod.argon2_available(), "argon2-cffi deve estar instalada no ambiente de teste"
    assert vault.kdf() == KDF_ARGON2ID
    data = json.loads(vault.path.read_text())
    assert data["argon2"] == {"t": 3, "m_kib": 65536, "p": 4}


def test_roundtrip_argon2(vault):
    vault.set("api", "sk-super-secreto-000111", PASS)
    assert vault.get("api", PASS) == "sk-super-secreto-000111"
    assert "sk-super-secreto" not in vault.path.read_text()


def test_migration_pbkdf2_to_argon2(tmp_path, clock, monkeypatch):
    path = tmp_path / "vault.json"
    monkeypatch.setattr(vmod, "_HAS_ARGON2", False)   # força cofre legado v1
    legacy = Vault(path, clock=clock)
    legacy.init(PASS)
    legacy.set("chave", "valor-legado", PASS)
    assert legacy.kdf() == KDF_PBKDF2
    monkeypatch.setattr(vmod, "_HAS_ARGON2", True)    # lib "instalada"
    v2 = Vault(path, clock=clock)
    assert v2.get("chave", PASS) == "valor-legado"    # unlock migra
    assert v2.kdf() == KDF_ARGON2ID
    assert v2.get("chave", PASS) == "valor-legado"    # pós-migração íntegro


def test_downgrade_fail_closed(vault, clock, monkeypatch):
    vault.set("x", "y-000000000", PASS)
    monkeypatch.setattr(vmod, "_HAS_ARGON2", False)
    v = Vault(vault.path, clock=clock)
    with pytest.raises(VaultError, match="argon2"):
        v.get("x", PASS)


def test_lockout_progressivo(vault, clock):
    for _ in range(3):                       # 3 falhas livres
        with pytest.raises(VaultLocked):
            vault.get("nada", "errada-000000")
    with pytest.raises(VaultLocked):         # 4a falha registra e arma 2s
        vault.get("nada", "errada-000000")
    with pytest.raises(VaultLockedOut) as ei:  # bloqueado ANTES de validar
        vault.get("nada", PASS)
    assert 0 < ei.value.retry_in <= 2
    clock.advance(2.1)
    vault.set("ok", "valor-0000000", PASS)   # espera cumprida + sucesso => reset
    with pytest.raises(VaultLocked):         # 1 falha pós-reset: livre de novo
        vault.get("nada", "errada-000000")
    vault.get("ok", PASS)


def test_lockout_dobra_e_persiste(tmp_path, clock):
    v = Vault(tmp_path / "v.json", clock=clock)
    v.init(PASS)
    for _ in range(4):
        with pytest.raises(VaultLocked):
            v.get("n", "errada-000000")
    clock.advance(2.1)                        # cumpre os 2s da 4a falha
    with pytest.raises(VaultLocked):          # 5a falha => 4s
        v.get("n", "errada-000000")
    v2 = Vault(v.path, clock=clock)           # NOVO objeto, mesmo estado em disco
    with pytest.raises(VaultLockedOut) as ei:
        v2.get("n", PASS)
    assert 2 < ei.value.retry_in <= 4


def test_lockout_estado_corrompido_fail_closed_recuperavel(vault, clock):
    lock = vault.path.with_name(vault.path.name + ".lockout")
    lock.write_text("{lixo::::")
    with pytest.raises(VaultLockedOut) as ei:
        vault.get("nada", PASS)
    assert ei.value.retry_in > LOCK_CAP_S - 5   # trava máxima
    clock.advance(LOCK_CAP_S + 1)
    vault.set("pos", "recuperado-000", PASS)    # autorrecupera com sucesso real
    assert vault.get("pos", PASS) == "recuperado-000"


@__import__("pytest").mark.skipif(
    __import__("os").name == "nt",
    reason="permissões POSIX (0600) não se aplicam ao Windows")
def test_lockout_arquivo_0600(vault):
    with pytest.raises(VaultLocked):
        vault.get("n", "errada-000000")
    lock = vault.path.with_name(vault.path.name + ".lockout")
    assert oct(lock.stat().st_mode & 0o777) == "0o600"
