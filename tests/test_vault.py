import stat

import os

import pytest

from nomos.kernel.vault import Vault, VaultError, VaultLocked

PW = "senha-forte-de-teste-123"
SEGREDO = "sk-EXEMPLO-simulado-abcdef123456"


def _vault(tmp_path):
    return Vault(tmp_path / "vault.json")


def test_roundtrip_set_get(tmp_path):
    v = _vault(tmp_path)
    v.init(PW)
    v.set("ANTHROPIC_API_KEY", SEGREDO, PW)
    assert v.get("ANTHROPIC_API_KEY", PW) == SEGREDO
    assert v.names() == ["ANTHROPIC_API_KEY"]


def test_segredo_nunca_em_claro_no_disco(tmp_path):
    v = _vault(tmp_path)
    v.init(PW)
    v.set("k", SEGREDO, PW)
    raw = (tmp_path / "vault.json").read_text()
    assert SEGREDO not in raw
    assert PW not in raw


def test_passphrase_errada_falha_fechado(tmp_path):
    v = _vault(tmp_path)
    v.init(PW)
    v.set("k", SEGREDO, PW)
    with pytest.raises(VaultLocked):
        v.get("k", "passphrase-incorreta-999")


def test_passphrase_minima(tmp_path):
    with pytest.raises(VaultError):
        _vault(tmp_path).init("curta")


@__import__("pytest").mark.skipif(os.name == "nt", reason="permissões POSIX (0600) não se aplicam ao Windows")
def test_permissoes_0600(tmp_path):
    v = _vault(tmp_path)
    v.init(PW)
    mode = stat.S_IMODE((tmp_path / "vault.json").stat().st_mode)
    assert mode == 0o600


def test_rotacao_invalida_passphrase_antiga(tmp_path):
    v = _vault(tmp_path)
    v.init(PW)
    v.set("k", SEGREDO, PW)
    nova = "outra-senha-forte-456"
    assert v.rotate(PW, nova) == 1
    assert v.get("k", nova) == SEGREDO
    with pytest.raises(VaultLocked):
        v.get("k", PW)


def test_init_duplicado_recusado(tmp_path):
    v = _vault(tmp_path)
    v.init(PW)
    with pytest.raises(VaultError):
        v.init(PW)


def test_cofre_corrompido_levanta_vaulterror_tratado(tmp_path):
    """Fase 0: JSON inválido no arquivo do cofre deve virar VaultError (com
    mensagem acionável), nunca um json.JSONDecodeError cru — quem chama (CLI)
    só sabe mostrar erro tratado para VaultError/VaultLocked."""
    v = _vault(tmp_path)
    v.init(PW)
    (tmp_path / "vault.json").write_text("{ isto nao é json valido ]]]")
    with pytest.raises(VaultError) as excinfo:
        v.get("qualquer", PW)
    assert not isinstance(excinfo.value, VaultLocked)
    assert "corrompido" in str(excinfo.value).lower()
    # fail-closed: nada foi reparado/reescrito no arquivo corrompido
    assert (tmp_path / "vault.json").read_text() == "{ isto nao é json valido ]]]"
