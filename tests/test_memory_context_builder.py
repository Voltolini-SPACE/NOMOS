"""MC28 — NOMOS Memory Engine: reconstrução de contexto (context_builder).

Cobre: contexto vazio útil, limite de tamanho, destaque de handoff e ordem por
prioridade. Puramente leitura — nunca grava.
"""
from nomos.memory import context_builder
from nomos.memory.engine import MemoryEngine


def _entry(content, priority="low", source="manual", scope="project", created="2026-01-01T00:00:00Z"):
    return {
        "id": "mem_x", "created_at": created, "source": source, "scope": scope,
        "priority": priority, "tags": [], "content": content, "links": [],
        "safety": {"contains_secret": False, "contains_personal_sensitive_data": False,
                   "human_review_required": False},
    }


def test_contexto_vazio_ainda_util():
    txt = context_builder.build([])
    assert isinstance(txt, str) and txt.strip()
    assert "vazia" in txt.lower()


def test_contexto_curto_e_limitado():
    grandes = [_entry("x" * 500, created=f"2026-01-01T00:00:{i:02d}Z") for i in range(40)]
    txt = context_builder.build(grandes, max_items=12, max_chars=1800)
    assert isinstance(txt, str)
    # muito menor que a soma bruta dos conteúdos (40 * 500 = 20000)
    assert len(txt) < 2600


def test_destaque_handoff():
    entradas = [
        _entry("nota comum", priority="low"),
        _entry("retomar missão MC28 amanhã", priority="high", source="handoff",
               created="2026-02-01T00:00:00Z"),
    ]
    txt = context_builder.build(entradas)
    assert "handoff" in txt.lower()
    assert "MC28" in txt


def test_prioridade_alta_primeiro():
    entradas = [
        _entry("baixa", priority="low", created="2026-03-01T00:00:00Z"),
        _entry("critica", priority="critical", created="2026-01-01T00:00:00Z"),
    ]
    txt = context_builder.build(entradas)
    assert txt.index("critica") < txt.index("baixa")


def test_context_via_engine(tmp_path):
    eng = MemoryEngine(base_dir=tmp_path / "mem")
    eng.add("preferencia registrada", apply=True, priority="high")
    txt = eng.context()
    assert "preferencia registrada" in txt
