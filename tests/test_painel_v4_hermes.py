"""Painel 4.0 — cockpit local: layout de app, health, api?secao, busca na
auditoria e a ÚNICA porta de ação (aprovações com token single-use).

Contratos novos deste arquivo (os antigos seguem nos testes MC29/MC33/v017,
que continuam passando SEM alteração):
- layout: sidebar + rail + bloco sistema; seções novas com âncoras estáveis;
- health/: JSON de sinal de vida para scripts;
- api/?secao=<chave>: recorte de uma seção; desconhecida ⇒ 404;
- audit/?q=: busca server-side sobre METADADOS, sempre escapada (anti-XSS);
- aprovações: form só existe com fila anexada E pendência; decidir consome
  token single-use (reuso/errado ⇒ 409); POST em qualquer outra rota ⇒ 405;
  fila desligada (False) ⇒ painel 100% somente leitura;
- headers de segurança (CSP/nosniff/no-referrer/no-store) em toda resposta;
- token jamais aparece na API/JSON — só no HTML do lado aprovador.
"""
import io
import json
import urllib.error
import urllib.request

import pytest

from nomos.cognition import motores
from nomos.interface.painel_web import DashboardServer, dados_dashboard, render_html
from nomos.kernel.approvals import ApprovalQueue
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
# 1. layout de app: sidebar, rail, sistema — e âncoras novas estáveis
# ---------------------------------------------------------------------------
def test_layout_app_abas_sidebar_e_sysbox(nomos_home):
    # MC37: layout em ABAS (uma por vez, sem rail). O que o rail mostrava
    # (motor ao vivo, atenção, atividade) migrou para a aba "visão geral".
    corpo = render_html(dados_dashboard(_ctx(nomos_home)))
    assert 'class="sidebar"' in corpo
    assert 'class="aba' in corpo and 'data-aba="visao"' in corpo   # abas
    assert 'class="rail"' not in corpo                             # rail removido
    assert 'class="sysbox"' in corpo            # bloco Sistema na sidebar
    assert 'class="menu"' in corpo and "aria-label" in corpo
    assert "motor ao vivo" in corpo             # migrou p/ visão geral
    assert "atividade recente" in corpo         # idem (antes no rail)
    # marca congelada segue intacta no novo layout
    assert "--neon:#5AF78E" in corpo and "#0A0F0D" in corpo


def test_ancoras_novas_apontam_para_secoes_que_existem(nomos_home):
    corpo = render_html(dados_dashboard(_ctx(nomos_home)))
    for anc in ("status", "aprovacoes", "rotinas", "capacidades",
                "sistema", "ajuda"):
        assert f'href="#{anc}"' in corpo, f"nav sem link p/ {anc}"
        assert f'id="{anc}"' in corpo, f"seção sem âncora id={anc}"


def test_secao_sistema_e_ajuda_com_conteudo_real(nomos_home):
    d = dados_dashboard(_ctx(nomos_home))
    assert d["sistema"]["python"] and d["sistema"]["plataforma"]
    corpo = render_html(d)
    assert "Ajuda rápida" in corpo and "nomos doutor" in corpo
    assert "as leis da casa" in corpo
    assert d["sistema"]["python"] in corpo      # dado real, não enfeite


def test_roteador_vivo_na_visao_geral(nomos_home):
    # MC37: "motor ao vivo" saiu do rail e vive no bloco de visão geral
    d = dados_dashboard(_ctx(nomos_home))
    assert d["roteador_vivo"], "roteador_vivo deveria listar as modalidades"
    mods = {r["modalidade"] for r in d["roteador_vivo"]}
    assert "texto" in mods
    corpo = render_html(d)
    # MC37.1: com tudo mockado off, a honestidade continua — agora recolhida
    # num <details> ("nenhum motor pronto ainda") em vez de 13 linhas
    assert "sem motor pronto" in corpo


# ---------------------------------------------------------------------------
# 2. health/ — sinal de vida para scripts e monitoramento
# ---------------------------------------------------------------------------
def test_health_json(nomos_home):
    srv = DashboardServer(_ctx(nomos_home))
    url = srv.start()
    try:
        status, corpo, hdrs = _get(f"{url}health/")
        assert status == 200 and "application/json" in hdrs["Content-Type"]
        dados = json.loads(corpo)
        assert dados["ok"] is True
        assert dados["versao"] and "aprovacoes_pendentes" in dados
        # sinais reais para scripts/integrações (não só "estou vivo")
        assert dados["status_geral"] in {"PRONTO", "PARCIAL", "BLOQUEADO"}
        assert dados["proximo_passo"]
        assert isinstance(dados["avisos"], list)
        assert isinstance(dados["saudavel"], bool)
        assert "motores_prontos" in dados
    finally:
        srv.stop()


def test_health_avisos_refletem_pendencias_reais(nomos_home):
    """Os avisos do health são SINAIS verdadeiros: criam-se pendências,
    eles aparecem; sem pendências de aviso, a lista corresponde."""
    from nomos.cognition.memory import Memory
    ctx = _ctx(nomos_home)
    Memory(nomos_home / "memory.db").propor_candidata("fato a revisar")
    fila = ApprovalQueue(nomos_home / "approvals", audit=ctx["audit"])
    fila.request("A2_WRITE_LOCAL", "arquivo.txt", "gravar")
    srv = DashboardServer(ctx)
    url = srv.start()
    try:
        _, corpo, _ = _get(f"{url}health/")
        dados = json.loads(corpo)
        texto = " · ".join(dados["avisos"])
        assert "memória" in texto            # candidata proposta acima
        assert "aprovação" in texto          # pendência criada acima
        assert dados["saudavel"] is False    # há avisos ⇒ não "saudável"
        assert dados["aprovacoes_pendentes"] == 1
    finally:
        srv.stop()


# ---------------------------------------------------------------------------
# 3. api/?secao= — recorte de uma seção só
# ---------------------------------------------------------------------------
def test_api_por_secao_e_secao_desconhecida(nomos_home):
    srv = DashboardServer(_ctx(nomos_home))
    url = srv.start()
    try:
        status, corpo, hdrs = _get(f"{url}api/?secao=motores")
        assert status == 200 and "application/json" in hdrs["Content-Type"]
        dados = json.loads(corpo)
        assert dados["secao"] == "motores" and isinstance(dados["dados"], list)
        assert "politica" not in corpo          # recorte é recorte
        with pytest.raises(urllib.error.HTTPError) as e404:
            urllib.request.urlopen(f"{url}api/?secao=nao-existe", timeout=5)  # nosec B310
        assert e404.value.code == 404
        assert "disponiveis" in e404.value.read().decode()
    finally:
        srv.stop()


# ---------------------------------------------------------------------------
# 4. audit/?q= — busca server-side, escapada
# ---------------------------------------------------------------------------
def test_audit_busca_filtra_e_escapa(nomos_home):
    ctx = _ctx(nomos_home)
    ctx["audit"].append("painel.alfa", origem="teste")
    ctx["audit"].append("painel.beta", origem="teste")
    ctx["audit"].append("outro.evento", origem="teste")
    srv = DashboardServer(ctx)
    url = srv.start()
    try:
        _, com_filtro, _ = _get(f"{url}audit/?q=painel.alfa")
        assert "painel.alfa" in com_filtro
        assert "outro.evento" not in com_filtro     # filtrou de verdade
        assert "filtro ativo" in com_filtro
        # XSS pela query: sai escapado, nunca cru
        _, xss, _ = _get(f"{url}audit/?q=%3Cscript%3Ealert(1)%3C/script%3E")
        assert "<script>alert(1)</script>" not in xss
        assert "&lt;script&gt;" in xss
        # sem filtro: tudo aparece
        _, sem, _ = _get(f"{url}audit/")
        assert "painel.alfa" in sem and "outro.evento" in sem
    finally:
        srv.stop()


# ---------------------------------------------------------------------------
# 5. aprovações — a única porta de ação, com o gate de verdade
# ---------------------------------------------------------------------------
def test_sem_fila_nao_ha_form_nem_post(nomos_home):
    ctx = _ctx(nomos_home)
    srv = DashboardServer(ctx, fila_aprovacoes=False)   # somente leitura
    url = srv.start()
    try:
        _, corpo, _ = _get(url)
        assert "<form" not in corpo
        req = urllib.request.Request(f"{url}aprovacoes/decidir",
                                     data=b"id=x&token=y&action=aprovar",
                                     method="POST")
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=5)  # nosec B310
        assert e.value.code == 405
    finally:
        srv.stop()


def test_fila_anexada_mostra_pendencia_e_decide_aprovando(nomos_home):
    ctx = _ctx(nomos_home)
    fila = ApprovalQueue(nomos_home / "approvals", audit=ctx["audit"])
    rid, _token_solicitante = fila.request("A2_WRITE_LOCAL",
                                           "~/Documentos/plano.md",
                                           "salvar o plano aprovado")
    srv = DashboardServer(ctx)      # fila padrão: a MESMA (file-based)
    url = srv.start()
    try:
        _, corpo, _ = _get(url)
        assert "Aprovações — você decide" in corpo
        assert "A2_WRITE_LOCAL" in corpo and "plano.md" in corpo
        assert "APROVAR" in corpo and "NEGAR" in corpo
        token = fila.token_of(rid)
        req = urllib.request.Request(
            f"{url}aprovacoes/decidir",
            data=f"id={rid}&token={token}&action=aprovar".encode(),
            method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:  # nosec B310
            # PRG: 303 → volta ao painel (urllib segue o redirect)
            assert r.status == 200
        assert fila.get(rid).status == "aprovada"
        # reuso do token consumido ⇒ 409 (single-use de verdade)
        req2 = urllib.request.Request(
            f"{url}aprovacoes/decidir",
            data=f"id={rid}&token={token}&action=aprovar".encode(),
            method="POST")
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req2, timeout=5)  # nosec B310
        assert e.value.code == 409
    finally:
        srv.stop()


def test_token_errado_e_acao_invalida_recusados(nomos_home):
    ctx = _ctx(nomos_home)
    fila = ApprovalQueue(nomos_home / "approvals", audit=ctx["audit"])
    rid, _ = fila.request("A3_EXEC", "script.sh", "rodar")
    srv = DashboardServer(ctx)
    url = srv.start()
    try:
        req = urllib.request.Request(
            f"{url}aprovacoes/decidir",
            data=f"id={rid}&token=token-chutado&action=negar".encode(),
            method="POST")
        with pytest.raises(urllib.error.HTTPError) as e1:
            urllib.request.urlopen(req, timeout=5)  # nosec B310
        assert e1.value.code == 409                 # token errado: fila recusa
        assert fila.get(rid).status == "pendente"   # e NADA mudou
        token = fila.token_of(rid)
        req2 = urllib.request.Request(
            f"{url}aprovacoes/decidir",
            data=f"id={rid}&token={token}&action=explodir".encode(),
            method="POST")
        with pytest.raises(urllib.error.HTTPError) as e2:
            urllib.request.urlopen(req2, timeout=5)  # nosec B310
        assert e2.value.code == 400                 # ação fora do vocabulário
        # POST em qualquer outra rota segue proibido mesmo com fila anexada
        req3 = urllib.request.Request(f"{url}api/", data=b"x", method="POST")
        with pytest.raises(urllib.error.HTTPError) as e3:
            urllib.request.urlopen(req3, timeout=5)  # nosec B310
        assert e3.value.code == 405
    finally:
        srv.stop()


def test_negar_tambem_funciona_e_audita(nomos_home):
    ctx = _ctx(nomos_home)
    fila = ApprovalQueue(nomos_home / "approvals", audit=ctx["audit"])
    rid, _ = fila.request("A4_NET", "https://exemplo.com", "buscar dados")
    srv = DashboardServer(ctx)
    url = srv.start()
    try:
        token = fila.token_of(rid)
        req = urllib.request.Request(
            f"{url}aprovacoes/decidir",
            data=f"id={rid}&token={token}&action=negar".encode(),
            method="POST")
        with urllib.request.urlopen(req, timeout=5):  # nosec B310
            pass
        assert fila.get(rid).status == "negada"
        trilha = (nomos_home / "logs" / "audit.jsonl").read_text()
        assert "approval.negada" in trilha or "approval" in trilha
    finally:
        srv.stop()


def test_alvo_com_html_sai_escapado_no_card_de_aprovacao(nomos_home):
    ctx = _ctx(nomos_home)
    fila = ApprovalQueue(nomos_home / "approvals", audit=ctx["audit"])
    fila.request("A2_WRITE_LOCAL", "<script>alert(1)</script>", "xss?")
    srv = DashboardServer(ctx)
    url = srv.start()
    try:
        _, corpo, _ = _get(url)
        assert "<script>alert(1)</script>" not in corpo   # nunca cru
        assert "&lt;script&gt;" in corpo                  # escapado
    finally:
        srv.stop()


def test_token_jamais_vaza_para_api_ou_dados(nomos_home):
    ctx = _ctx(nomos_home)
    fila = ApprovalQueue(nomos_home / "approvals", audit=ctx["audit"])
    rid, _ = fila.request("A2_WRITE_LOCAL", "arquivo.txt", "gravar")
    token = fila.token_of(rid)
    srv = DashboardServer(ctx)
    url = srv.start()
    try:
        assert token not in json.dumps(dados_dashboard(ctx), default=str)
        _, api, _ = _get(f"{url}api/")
        assert token not in api                 # API: contagem, nunca o token
        assert '"pendentes": 1' in api
    finally:
        srv.stop()


# ---------------------------------------------------------------------------
# 6. headers de segurança em toda resposta
# ---------------------------------------------------------------------------
def test_headers_de_seguranca_presentes(nomos_home):
    srv = DashboardServer(_ctx(nomos_home))
    url = srv.start()
    try:
        for rota in ("", "api/", "health/", "audit/"):
            _, _, hdrs = _get(f"{url}{rota}")
            assert "default-src 'none'" in hdrs.get("Content-Security-Policy", ""), rota
            assert hdrs.get("X-Content-Type-Options") == "nosniff", rota
            assert hdrs.get("Referrer-Policy") == "no-referrer", rota
            assert hdrs.get("Cache-Control") == "no-store", rota
    finally:
        srv.stop()


# ---------------------------------------------------------------------------
# 7. compat: render_html puro (sem fila) continua sem nenhum <form>
# ---------------------------------------------------------------------------
def test_render_sem_fila_segue_sem_form(nomos_home):
    corpo = render_html(dados_dashboard(_ctx(nomos_home)))
    assert "<form" not in corpo and 'method="post"' not in corpo.lower()
    # e com fila anexada porém VAZIA, também não há form (nada a decidir)
    corpo2 = render_html(dados_dashboard(_ctx(nomos_home)), aprovacoes=[])
    assert "<form" not in corpo2
    assert "nenhuma solicitação pendente" in corpo2
