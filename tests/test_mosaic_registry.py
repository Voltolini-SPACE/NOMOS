"""NOMOS Mosaic — registro de telas isoladas."""
import os

import pytest

from nomos.mosaic.registry import MosaicRegistry


def test_add_normaliza_url_e_cria_perfil_isolado(tmp_path):
    reg = MosaicRegistry(base_dir=tmp_path / "mosaic")
    s = reg.add("mail.google.com", "Gmail")
    assert s.url == "https://mail.google.com"          # normaliza esquema
    assert s.label == "Gmail"
    assert os.path.isdir(s.profile_dir)                # perfil próprio criado


def test_perfis_sao_isolados(tmp_path):
    reg = MosaicRegistry(base_dir=tmp_path / "mosaic")
    a = reg.add("mail.google.com")
    b = reg.add("outlook.office.com")
    c = reg.add("instagram.com")
    assert len({a.profile_dir, b.profile_dir, c.profile_dir}) == 3
    assert reg.profiles_isolated() is True


def test_remove_e_list(tmp_path):
    reg = MosaicRegistry(base_dir=tmp_path / "mosaic")
    a = reg.add("a.com")
    reg.add("b.com")
    assert len(reg.list()) == 2
    assert reg.remove(a.id) is True
    assert reg.remove(a.id) is False                   # já não existe
    assert len(reg.list()) == 1


def test_url_vazia_recusada(tmp_path):
    reg = MosaicRegistry(base_dir=tmp_path / "mosaic")
    with pytest.raises(ValueError):
        reg.add("   ")


def test_list_vazia_sem_arquivo(tmp_path):
    reg = MosaicRegistry(base_dir=tmp_path / "inexistente")
    assert reg.list() == []


@pytest.mark.skipif(os.name == "nt", reason="permissões POSIX 0600 não se aplicam ao Windows")
def test_screens_json_0600(tmp_path):
    reg = MosaicRegistry(base_dir=tmp_path / "mosaic")
    reg.add("a.com")
    assert oct(reg.screens_path.stat().st_mode & 0o777) == "0o600"
