"""MC28 — NOMOS Memory Engine: camada de armazenamento (store).

Cobre: hash gerado, hash determinístico, hash ignora o próprio campo, formato
de id, histórico append-only, leitura tolerante e permissão 0600.
"""
import os
import re

import pytest

from nomos.memory import store

CORE = {
    "id": "mem_x",
    "created_at": "2026-01-01T00:00:00Z",
    "source": "manual",
    "scope": "project",
    "priority": "low",
    "tags": [],
    "content": "memória objetiva",
    "links": [],
    "safety": {
        "contains_secret": False,
        "contains_personal_sensitive_data": False,
        "human_review_required": False,
    },
}


def test_hash_gerado():
    e = store.finalize_entry(CORE)
    assert re.fullmatch(r"[0-9a-f]{64}", e["hash"])          # SHA-256 hex


def test_hash_deterministico():
    assert store.compute_hash(CORE) == store.compute_hash(dict(CORE))


def test_hash_ignora_o_proprio_campo_hash():
    com_hash = dict(CORE, hash="valor-qualquer")
    assert store.compute_hash(com_hash) == store.compute_hash(CORE)


def test_new_id_formato():
    assert re.fullmatch(r"mem_\d{14}_[0-9a-f]{8}", store.new_id("abc"))


def test_now_iso_formato():
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", store.now_iso())


def test_append_only_preserva_historico(tmp_path):
    st = store.MemoryStore(tmp_path / "mem")
    e1 = store.finalize_entry(dict(CORE, id=store.new_id("um"), content="um"))
    e2 = store.finalize_entry(dict(CORE, id=store.new_id("dois"), content="dois"))
    st.append_raw(e1)
    bytes_apos_1 = st.paths.raw.read_bytes()
    st.append_raw(e2)
    # a segunda escrita só ANEXA: os bytes iniciais continuam intactos
    assert st.paths.raw.read_bytes().startswith(bytes_apos_1)
    assert len(st.read_raw()) == 2


def test_read_missing_retorna_vazio(tmp_path):
    st = store.MemoryStore(tmp_path / "inexistente")
    assert st.read_raw() == []
    assert st.read_compacted() == []
    assert not (tmp_path / "inexistente").exists()   # leitura não cria nada


@pytest.mark.skipif(os.name == "nt", reason="permissões POSIX 0600 não se aplicam ao Windows")
def test_arquivo_0600(tmp_path):
    st = store.MemoryStore(tmp_path / "mem")
    st.append_raw(store.finalize_entry(CORE))
    assert oct(st.paths.raw.stat().st_mode & 0o777) == "0o600"
