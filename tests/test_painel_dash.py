"""NOMOS Dash (MC39) — a ferramenta própria de dashboard ao vivo.

Contratos:
- ``dash/`` serve o shell ESTÁTICO (nenhum dado interpolado — tudo chega
  por polling same-origin e entra via textContent, XSS-safe por projeto);
- widgets essenciais presentes (glanceability: status, aprovações,
  memória, cadeia, sparkline 24h, motores, avisos);
- CSP ganhou ``connect-src 'self'`` (fetch SÓ da própria origem) e mantém
  todo o resto restritivo;
- ``atividade_24h`` existe nos dados/API: 24 buckets/hora REAIS da trilha;
- ``health/`` ganhou uptime (uptime_s/uptime_hum);
- dash não tem POST (405) e segredo errado ⇒ 404, como todo o painel;
- sidebar do painel linka o dash.
"""
import io
import json
import urllib.error
import urllib.request

import pytest

from nomos.cognition import motores
from nomos.interface.painel_web import (
    DashboardServer,
    _uptime_humano,
    dados_dashboard,
    render_dash,
    render_html,
)
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import PolicyEngine


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


def _get(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as r:  # nosec B310 - loopback
        return r.status, r.read().decode(), dict(r.headers)


# ---------------------------------------------------------------------------
# 1. shell do dash: estático, com os widgets essenciais
# ---------------------------------------------------------------------------
def test_dash_serve_shell_com_widgets(nomos_home):
    srv = DashboardServer(_ctx(nomos_home))
    url = srv.start()
    try:
        status, corpo, hdrs = _get(f"{url}dash/")
        assert status == 200 and "text/html" in hdrs["Content-Type"]
        assert "NOMOS DASH" in corpo
        for wid in ("id=\"status\"", "id=\"aprov\"", "id=\"memrev\"",
                    "id=\"cadeia\"", "id=\"spark\"", "id=\"motores\"",
                    "id=\"avisos\"", "id=\"estado\"", "id=\"pausa\""):
            assert wid in corpo, f"widget ausente: {wid}"
        # honestidade e lei da casa declaradas na própria tela
        assert "só LÊ" in corpo and "gate" in corpo
    finally:
        srv.stop()


def test_dash_shell_nao_interpola_dados_do_usuario(nomos_home):
    """XSS por projeto: o shell é estático — nomes de eventos/alvos NUNCA
    entram no HTML do dash (só via JSON + textContent no cliente)."""
    ctx = _ctx(nomos_home)
    ctx["audit"].append("<script>alert(1)</script>", origem="xss")
    corpo = render_dash("1.0.0")
    assert "<script>alert(1)</script>" not in corpo
    srv = DashboardServer(ctx)
    url = srv.start()
    try:
        _, corpo_http, _ = _get(f"{url}dash/")
        assert "<script>alert(1)</script>" not in corpo_http
    finally:
        srv.stop()


# ---------------------------------------------------------------------------
# 2. CSP: connect-src 'self' em toda resposta; resto continua fechado
# ---------------------------------------------------------------------------
def test_csp_ganhou_connect_src_self(nomos_home):
    srv = DashboardServer(_ctx(nomos_home))
    url = srv.start()
    try:
        for rota in ("", "dash/", "api/", "health/"):
            _, _, hdrs = _get(f"{url}{rota}")
            csp = hdrs.get("Content-Security-Policy", "")
            assert "connect-src 'self'" in csp, rota
            assert "default-src 'none'" in csp, rota
            assert "frame-ancestors 'none'" in csp, rota
    finally:
        srv.stop()


# ---------------------------------------------------------------------------
# 3. atividade_24h: série REAL da trilha (24 buckets por hora)
# ---------------------------------------------------------------------------
def test_atividade_24h_conta_eventos_reais(nomos_home):
    ctx = _ctx(nomos_home)
    for i in range(5):
        ctx["audit"].append(f"evento.{i}", origem="dash")
    d = dados_dashboard(ctx)
    a = d["atividade_24h"]
    assert len(a["buckets"]) == 24
    assert a["total"] >= 5                    # os 5 de agora estão lá
    assert a["buckets"][23] >= 5              # bucket 23 = hora atual
    srv = DashboardServer(ctx)
    url = srv.start()
    try:
        _, corpo, _ = _get(f"{url}api/?secao=atividade_24h")
        via_api = json.loads(corpo)["dados"]
        assert len(via_api["buckets"]) == 24 and via_api["total"] >= 5
    finally:
        srv.stop()


# ---------------------------------------------------------------------------
# 4. health: uptime real
# ---------------------------------------------------------------------------
def test_health_tem_uptime(nomos_home):
    srv = DashboardServer(_ctx(nomos_home))
    url = srv.start()
    try:
        _, corpo, _ = _get(f"{url}health/")
        h = json.loads(corpo)
        assert isinstance(h["uptime_s"], int) and h["uptime_s"] >= 0
        assert h["uptime_hum"]
    finally:
        srv.stop()


def test_uptime_humano_formata():
    assert _uptime_humano(12) == "12s"
    assert _uptime_humano(90) == "1m30s"
    assert _uptime_humano(3661) == "1h01m"
    assert _uptime_humano(-5) == "0s"          # nunca negativo


# ---------------------------------------------------------------------------
# 5. leis do painel valem no dash: sem POST, segredo manda
# ---------------------------------------------------------------------------
def test_dash_sem_post_e_com_segredo(nomos_home):
    srv = DashboardServer(_ctx(nomos_home))
    url = srv.start()
    try:
        req = urllib.request.Request(f"{url}dash/", data=b"x", method="POST")
        with pytest.raises(urllib.error.HTTPError) as e1:
            urllib.request.urlopen(req, timeout=5)  # nosec B310
        assert e1.value.code == 405
        base_errada = url.rsplit("/d/", 1)[0] + "/d/segredo-errado/dash/"
        with pytest.raises(urllib.error.HTTPError) as e2:
            urllib.request.urlopen(base_errada, timeout=5)  # nosec B310
        assert e2.value.code == 404
    finally:
        srv.stop()


# ---------------------------------------------------------------------------
# 6. o painel aponta para o dash
# ---------------------------------------------------------------------------
def test_sidebar_do_painel_linka_o_dash(nomos_home):
    corpo = render_html(dados_dashboard(_ctx(nomos_home)))
    assert 'href="dash/"' in corpo and "dash ao vivo" in corpo
