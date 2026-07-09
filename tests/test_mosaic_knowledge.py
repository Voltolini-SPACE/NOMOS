"""NOMOS Mosaic — vistoria (knowledge store)."""
from nomos.mosaic.knowledge import Knowledge, KnowledgeStore


def test_save_get_roundtrip(tmp_path):
    ks = KnowledgeStore(tmp_path)
    ks.save(Knowledge(screen_id="scr_1", url="https://x.com",
                      scanned_at="2026-01-01T00:00:00Z", title="Inbox",
                      summary="2 não lidos", signals={"unread": 2},
                      image="data:image/svg+xml;base64,AAA"))
    k = ks.get("scr_1")
    assert k is not None
    assert k.signals["unread"] == 2
    assert k.image.startswith("data:image/")


def test_all_e_get_ausente(tmp_path):
    ks = KnowledgeStore(tmp_path)
    assert ks.get("nao_existe") is None
    assert ks.all() == []
    ks.save(Knowledge("scr_a", "https://a.com", "2026-01-01T00:00:00Z"))
    ks.save(Knowledge("scr_b", "https://b.com", "2026-01-01T00:00:00Z"))
    assert len(ks.all()) == 2
