"""MC29 — Painel web local: seções de evidências e política viva.

O painel continua loopback-only e somente leitura; agora mostra também os
pacotes de evidências (com verificação real de integridade) e a política de
permissões A0–A6 lida do código (contrato vivo, não cópia).
"""
import io
from pathlib import Path

import pytest

from nomos.cognition import motores
from nomos.interface.painel_web import dados_dashboard, render_html
from nomos.kernel import evidencia as ev
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


# 1. dados: chaves novas com contrato vivo
def test_dados_incluem_politica_e_evidencias(nomos_home):
    d = dados_dashboard(_ctx(nomos_home))
    assert d["evidencias"] == []
    pol = d["politica"]
    assert pol["execucao_real_council"] is False
    assert pol["flags_proibidas"] == 10
    assert pol["regras"]["A0_READ_LOCAL"] == "ALLOW"
    assert pol["regras"]["A6_DESTRUCTIVE"] == "DENY"


# 2. render: política visível e honesta
def test_render_mostra_politica_e_dry_run(nomos_home):
    corpo = render_html(dados_dashboard(_ctx(nomos_home)))
    assert "Política de permissões (A0–A6)" in corpo
    assert "A6_DESTRUCTIVE" in corpo and "DENY" in corpo
    assert "DESLIGADA (dry-run apenas)" in corpo
    assert "aprovação humana obrigatória" in corpo


# 3. evidências: pacote real aparece com verificação de integridade REAL
def test_render_lista_evidencias_com_integridade(nomos_home):
    ctx = _ctx(nomos_home)
    pacote = ev.gerar_pacote(nomos_home / "evidencias", "missão painel",
                             status="PASS")
    corpo = render_html(dados_dashboard(ctx))
    assert pacote.name in corpo and "íntegro" in corpo
    # adulterou => o painel conta a verdade
    (pacote / "RELATORIO.md").write_text("adulterado", encoding="utf-8")
    corpo2 = render_html(dados_dashboard(ctx))
    assert "NÃO confere" in corpo2


# 4. sem pacotes: orienta o comando certo
def test_sem_evidencias_orienta_comando(nomos_home):
    corpo = render_html(dados_dashboard(_ctx(nomos_home)))
    assert "nomos evidencia criar" in corpo


# 4b. MC30-A4: catálogo de capacidades no painel + auto-refresh opt-in
def test_painel_mostra_capacidades_do_catalogo(nomos_home):
    import shutil
    exemplo = Path(__file__).resolve().parent.parent / "examples/skills/busca-arquivos"
    destino = nomos_home / "skills" / "busca-arquivos"
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(exemplo, destino)
    corpo = render_html(dados_dashboard(_ctx(nomos_home)))
    assert "Capacidades (catálogo)" in corpo
    assert "busca-arquivos" in corpo and "risco" in corpo


def test_painel_refresh_opt_in_e_validado(nomos_home):
    import urllib.request

    from nomos.interface.painel_web import DashboardServer
    srv = DashboardServer(_ctx(nomos_home))
    url = srv.start()
    try:
        with urllib.request.urlopen(f"{url}?refresh=10", timeout=5) as r:  # nosec B310
            com = r.read().decode()
        assert 'http-equiv="refresh" content="10"' in com
        with urllib.request.urlopen(url, timeout=5) as r2:  # nosec B310
            sem = r2.read().decode()
        assert "http-equiv=\"refresh\"" not in sem      # padrão: sem refresh
        with urllib.request.urlopen(f"{url}?refresh=2", timeout=5) as r3:  # nosec B310
            fora = r3.read().decode()
        assert "http-equiv=\"refresh\"" not in fora     # fora da faixa: ignora
    finally:
        srv.stop()


# 5. rota /ev/<pacote>: serve o relatório; nome estrito; sem traversal
def test_painel_serve_relatorio_de_evidencia(nomos_home):
    import urllib.error
    import urllib.request

    from nomos.interface.painel_web import DashboardServer
    ctx = _ctx(nomos_home)
    pacote = ev.gerar_pacote(nomos_home / "evidencias", "abrir no painel",
                             status="PASS")
    srv = DashboardServer(ctx)
    url = srv.start()
    try:
        # dashboard linka o relatório
        with urllib.request.urlopen(url, timeout=5) as r:  # nosec B310 - loopback
            corpo = r.read().decode()
        assert f'href="ev/{pacote.name}/"' in corpo
        # relatório servido como texto
        with urllib.request.urlopen(f"{url}ev/{pacote.name}/", timeout=5) as r2:  # nosec B310
            rel = r2.read().decode()
        assert r2.status == 200 and "Evidência" in rel
        assert "text/plain" in r2.headers.get("Content-Type", "")
        # nome fora do padrão => 404
        with pytest.raises(urllib.error.HTTPError) as e1:
            urllib.request.urlopen(f"{url}ev/nao-e-pacote/", timeout=5)  # nosec B310
        assert e1.value.code == 404
        # traversal => 404 (nunca sai de ~/.nomos/evidencias)
        with pytest.raises(urllib.error.HTTPError) as e2:
            urllib.request.urlopen(
                f"{url}ev/EVIDENCIA_x/%2e%2e/%2e%2e/policy.json", timeout=5)  # nosec B310
        assert e2.value.code == 404
    finally:
        srv.stop()
