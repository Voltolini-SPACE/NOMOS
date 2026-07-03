"""C3 — memória local persistente (SQLite/FTS5)."""
from nomos.cognition.memory import Memory

import pytest


@pytest.fixture()
def mem(tmp_path):
    return Memory(tmp_path / "memory.db")


def test_roundtrip_e_recencia(mem):
    a = mem.remember("user", "gosto de café coado")
    b = mem.remember("assistant", "anotado: café coado")
    assert mem.count() == 2
    recent = mem.recent(2)
    assert [r.id for r in recent] == [b, a]          # mais novo primeiro


def test_persistencia_entre_instancias(tmp_path):
    p = tmp_path / "m.db"
    m1 = Memory(p)
    m1.remember("note", "backup toda sexta")
    m1.close()
    m2 = Memory(p)
    assert m2.count() == 1
    assert "sexta" in m2.recent(1)[0].text


def test_recall_por_relevancia(mem):
    mem.remember("note", "a fatura da AWS vence dia 5")
    mem.remember("note", "reunião com investidores na quinta")
    mem.remember("note", "fatura do cartão corporativo paga")
    hits = mem.recall("fatura vencimento")
    assert hits and all("fatura" in h.text for h in hits[:2])


def test_recall_query_hostil_nao_injeta(mem):
    mem.remember("note", "texto qualquer")
    # operadores/aspas de FTS e SQL viram texto/token — não podem explodir
    for q in ['" OR 1=1 --', 'NEAR( a b )', 'x AND', '"; DROP TABLE memories;']:
        mem.recall(q)                                 # não levanta
    assert mem.count() == 1                           # tabela intacta


def test_forget(mem):
    i = mem.remember("note", "apagar depois")
    assert mem.forget(i) is True
    assert mem.forget(i) is False
    assert mem.count() == 0


def test_role_invalido(mem):
    with pytest.raises(ValueError):
        mem.remember("hacker", "x")


def test_arquivo_0600(tmp_path):
    p = tmp_path / "m.db"
    Memory(p)
    assert oct(p.stat().st_mode & 0o777) == "0o600"
