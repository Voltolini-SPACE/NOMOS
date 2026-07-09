"""MC28 — NOMOS Memory Engine: compactação (compactor).

Invariante central: a compactação NUNCA apaga nem altera o histórico bruto —
só deriva o arquivo compactado. Também: dry-run não grava, proveniência é
preservada e o plano é determinístico.
"""
from nomos.memory import compactor
from nomos.memory.engine import MemoryEngine


def _semear(base, n=3):
    eng = MemoryEngine(base_dir=base)
    for i in range(n):
        eng.add(f"memoria objetiva numero {i}", apply=True,
                scope="project", source="manual", priority="medium")
    return eng


def test_compactacao_preserva_historico_bruto(tmp_path):
    base = tmp_path / "mem"
    eng = _semear(base, 3)
    bruto_antes = eng.store.paths.raw.read_bytes()

    res = eng.compact(apply=True)

    assert res.applied is True
    # o BRUTO tem que ser idêntico byte a byte após compactar
    assert eng.store.paths.raw.read_bytes() == bruto_antes
    assert eng.store.paths.compacted.exists()
    assert len(res.plan.derived) >= 1


def test_compact_dry_run_nao_grava(tmp_path):
    base = tmp_path / "mem"
    eng = _semear(base, 2)
    res = eng.compact(apply=False)
    assert res.dry_run is True and res.applied is False
    assert not eng.store.paths.compacted.exists()   # dry-run não deixa derivado


def test_proveniencia_preservada(tmp_path):
    base = tmp_path / "mem"
    eng = _semear(base, 3)
    ids_bruto = {e["id"] for e in eng.list_entries()}
    res = eng.compact(apply=True)
    links = {lk for d in res.plan.derived for lk in d["links"]}
    assert links == ids_bruto            # todo id de origem aparece no derivado


def test_plano_deterministico(tmp_path):
    base = tmp_path / "mem"
    eng = _semear(base, 4)
    raw = eng.list_entries()
    p1 = compactor.plan(raw)
    p2 = compactor.plan(raw)
    assert p1.groups == p2.groups
    assert [d["links"] for d in p1.derived] == [d["links"] for d in p2.derived]


def test_grupos_por_escopo_e_fonte(tmp_path):
    base = tmp_path / "mem"
    eng = MemoryEngine(base_dir=base)
    eng.add("a", apply=True, scope="project", source="manual")
    eng.add("b", apply=True, scope="repo", source="repo_audit")
    res = eng.compact(apply=True)
    assert res.plan.groups == 2          # (project,manual) e (repo,repo_audit)
