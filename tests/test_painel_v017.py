"""v0.17 — painel local: loopback apenas, segredo na URL, somente leitura."""
import io
import urllib.error
import urllib.request

import pytest

from nomos.cognition import motores
from nomos.interface.painel_web import DashboardServer, dados_dashboard, render_html
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import PolicyEngine

SEGREDO_DO_USUARIO = "sk-CHAVE-QUE-NAO-PODE-VAZAR-123"


@pytest.fixture(autouse=True)
def _iso(nomos_home, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: [])
    monkeypatch.setattr(motores, "_http_ok", lambda *a, **k: False)
    monkeypatch.setattr("shutil.which", lambda *a, **k: None)
    motores.limpar_cache()
    yield
    motores.limpar_cache()


def _ctx(nomos_home):
    nomos_home.mkdir(parents=True, exist_ok=True)
    (nomos_home / "skills").mkdir(exist_ok=True)
    return {"home": nomos_home,
            "policy": PolicyEngine(nomos_home / "policy.json"),
            "audit": AuditLog(nomos_home / "logs" / "audit.jsonl"),
            "skills": nomos_home / "skills"}


def test_bind_fora_do_loopback_recusado(nomos_home):
    with pytest.raises(ValueError, match="127.0.0.1"):
        DashboardServer(_ctx(nomos_home), host="0.0.0.0")


def test_dados_e_render_sem_vazamento(nomos_home):
    ctx = _ctx(nomos_home)
    # um evento com padrão de segredo: a auditoria redige na entrada
    ctx["audit"].append("teste.evento", detalhe=f"token {SEGREDO_DO_USUARIO}")
    d = dados_dashboard(ctx)
    assert d["status_geral"] in {"PRONTO", "PARCIAL", "BLOQUEADO"}
    corpo = render_html(d)
    assert "STATUS GERAL" in corpo and "Check-up" in corpo
    assert SEGREDO_DO_USUARIO not in corpo        # painel nunca vaza segredo


def test_servidor_http_real(nomos_home):
    ctx = _ctx(nomos_home)
    srv = DashboardServer(ctx)
    url = srv.start()
    try:
        assert url.startswith("http://127.0.0.1:")
        # com o segredo: 200 e conteúdo
        with urllib.request.urlopen(url, timeout=5) as r:  # nosec B310 - teste loopback
            corpo = r.read().decode()
        assert r.status == 200 and "painel local" in corpo
        # sem o segredo: 404
        base = url.rsplit("/d/", 1)[0]
        with pytest.raises(urllib.error.HTTPError) as e1:
            urllib.request.urlopen(f"{base}/d/segredo-errado/", timeout=5)  # nosec B310
        assert e1.value.code == 404
        # POST: painel é somente leitura — 405
        req = urllib.request.Request(url, data=b"acao=mudar", method="POST")
        with pytest.raises(urllib.error.HTTPError) as e2:
            urllib.request.urlopen(req, timeout=5)  # nosec B310
        assert e2.value.code == 405
    finally:
        srv.stop()


def test_painel_mostra_rotinas_e_skills(nomos_home):
    ctx = _ctx(nomos_home)
    from nomos.simple import rotinas as rot
    rot.criar(nomos_home, "Briefing", "08:00", "briefing",
              ctx["policy"], approver=lambda dec: True)
    corpo = render_html(dados_dashboard(ctx))
    assert "Briefing" in corpo and "08:00" in corpo
    assert "nenhuma instalada" in corpo           # sem skills ainda


def test_painel_nunca_derruba_com_erro_interno(nomos_home, monkeypatch):
    ctx = _ctx(nomos_home)
    srv = DashboardServer(ctx)
    url = srv.start()
    try:
        import nomos.interface.painel_web as pw
        monkeypatch.setattr(pw, "dados_dashboard",
                            lambda c: (_ for _ in ()).throw(RuntimeError("boom")))
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(url, timeout=5)  # nosec B310
        assert e.value.code == 500
        assert "RuntimeError" in e.value.read().decode()
        assert "boom" not in str(e.value.read())   # sem detalhes internos
    finally:
        srv.stop()
