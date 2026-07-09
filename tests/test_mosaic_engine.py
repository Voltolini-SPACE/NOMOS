"""NOMOS Mosaic — orquestrador: dry-run, vistoria, painel, ação com aprovação."""
import re
from pathlib import Path

import nomos.mosaic as _pkg
from nomos.mosaic.engine import MosaicEngine

PKG_DIR = Path(_pkg.__file__).parent


def _eng_com_tela(tmp_path):
    eng = MosaicEngine(base_dir=tmp_path / "mosaic")   # DemoAdapter por padrão
    eng.add_screen("mail.google.com", "Gmail", apply=True)
    return eng, eng.list_screens()[0].id


def test_add_dry_run_nao_grava(tmp_path):
    eng = MosaicEngine(base_dir=tmp_path / "mosaic")
    r = eng.add_screen("mail.google.com")
    assert r["applied"] is False and r["dry_run"] is True
    assert eng.list_screens() == []


def test_add_apply_grava(tmp_path):
    eng = MosaicEngine(base_dir=tmp_path / "mosaic")
    r = eng.add_screen("mail.google.com", "Gmail", apply=True)
    assert r["applied"] is True
    assert len(eng.list_screens()) == 1


def test_scan_dry_nao_salva_apply_salva(tmp_path):
    eng, sid = _eng_com_tela(tmp_path)
    res = eng.scan(apply=False)
    assert res and res[0].ok and res[0].saved is False
    assert eng.knowledge.get(sid) is None
    res2 = eng.scan(apply=True)
    assert res2[0].saved is True
    k = eng.knowledge.get(sid)
    assert k is not None and k.signals            # sinais capturados


def test_render_panel_dry_vs_apply(tmp_path):
    eng, _ = _eng_com_tela(tmp_path)
    html, path = eng.render_panel(apply=False)
    assert "NOMOS Mosaic" in html and path is None
    assert not (eng.registry.base / "panel.html").exists()
    _, path2 = eng.render_panel(apply=True)
    assert path2 and Path(path2).exists()


def test_act_proposto_por_padrao(tmp_path):
    eng, sid = _eng_com_tela(tmp_path)
    r = eng.act(sid, "reply")
    assert r.reason == "PROPOSED" and r.applied is False


def test_act_apply_sem_approve_nao_executa(tmp_path):
    eng, sid = _eng_com_tela(tmp_path)
    r = eng.act(sid, "mark_read", approve=False, apply=True)
    assert r.applied is False and r.reason == "PROPOSED"   # gate de aprovação


def test_act_approve_apply_executa(tmp_path):
    eng, sid = _eng_com_tela(tmp_path)
    r = eng.act(sid, "reply", approve=True, apply=True)
    assert r.applied is True and r.reason == "APPLIED"
    assert (eng.registry.base / "actions.jsonl").exists()


def test_act_fail_closed_acao_desconhecida(tmp_path):
    eng, sid = _eng_com_tela(tmp_path)
    r = eng.act(sid, "DELETE_ALL", approve=True, apply=True)
    assert r.applied is False
    assert r.reason.endswith("FAIL_CLOSED")


def test_act_tela_inexistente(tmp_path):
    eng, _ = _eng_com_tela(tmp_path)
    assert eng.act("scr_naoexiste", "reply").reason == "SCREEN_NOT_FOUND"


def test_context_resume_conhecimento(tmp_path):
    eng, _ = _eng_com_tela(tmp_path)
    eng.scan(apply=True)
    ctx = eng.context()
    assert "mail.google.com" in ctx


def test_seed_demo_popula_e_vistoria(tmp_path):
    eng = MosaicEngine(base_dir=tmp_path / "m")
    r = eng.seed_demo(apply=True)
    assert r["applied"] is True and r["total"] >= 6
    hosts = {t["host"] for t in eng.build_tiles()}
    assert any("bb" in h for h in hosts)            # Banco do Brasil entrou
    assert any("whatsapp" in h for h in hosts)      # WhatsApp Web entrou
    # idempotente: rodar de novo não duplica
    assert eng.seed_demo(apply=True)["added"] == []


def test_seed_demo_dry_run_nao_grava(tmp_path):
    eng = MosaicEngine(base_dir=tmp_path / "m")
    r = eng.seed_demo(apply=False)
    assert r["applied"] is False and r["would_add"]
    assert eng.list_screens() == []


def test_demo_adapter_categorias():
    from nomos.mosaic.browser import DemoAdapter
    a = DemoAdapter()
    assert "messages" in a.scan("s", "https://web.whatsapp.com").signals
    assert "avisos" in a.scan("s", "https://bb.com.br").signals
    assert "notifications" in a.scan("s", "https://tiktok.com").signals
    assert "unread" in a.scan("s", "https://mail.google.com").signals


def test_modulo_sem_shell_exec():
    for p in PKG_DIR.glob("*.py"):
        src = p.read_text(encoding="utf-8")
        assert not re.search(r"(?m)^\s*(?:import|from)\s+subprocess\b", src), p.name
        assert not re.search(r"\bos\.system\s*\(", src), p.name
        assert not re.search(r"\b(?:os\.popen|Popen)\s*\(", src), p.name
        assert not re.search(r"\beval\s*\(", src), p.name
        assert not re.search(r"\bexec\s*\(", src), p.name
