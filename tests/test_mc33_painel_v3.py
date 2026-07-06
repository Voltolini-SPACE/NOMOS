"""MC33 — Painel 3.0: marca, navegação, KPIs e seções novas (read-only)."""
import io

import pytest

from nomos.cognition import motores
from nomos.interface.painel_web import dados_dashboard, render_html
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


# 1. identidade da marca congelada no painel (paleta + monospace)
def test_painel_usa_marca_congelada(nomos_home):
    corpo = render_html(dados_dashboard(_ctx(nomos_home)))
    assert "--neon:#5AF78E" in corpo and "#0A0F0D" in corpo   # paleta congelada
    assert "monospace" in corpo                                # tipografia
    assert 'class="kpis"' in corpo                             # faixa de KPIs
    assert "<nav" in corpo and 'aria-label' in corpo           # nav acessível


# 2. navegação por âncoras aponta para seções que existem
def test_nav_ancoras_batem_com_secoes(nomos_home):
    corpo = render_html(dados_dashboard(_ctx(nomos_home)))
    for ancora in ("checkup", "motores", "skills", "agentes", "mcp",
                   "conversas", "memoria", "evidencias", "politica", "auditoria"):
        assert f'href="#{ancora}"' in corpo, f"nav sem link p/ {ancora}"
        assert f'id="{ancora}"' in corpo, f"seção sem âncora id={ancora}"


# 3. seções novas: agentes, mcp, conversas
def test_secao_mcp_mostra_servidor_e_confiaveis(nomos_home):
    from nomos.interface import mcp_catalogo as cat
    ctx = _ctx(nomos_home)
    cat.confiar(nomos_home, {"nome": "fs-local", "comando": ["x"],
                             "nivel_padrao": "A0", "tools": {}})
    corpo = render_html(dados_dashboard(ctx))
    assert "MCP — Model Context Protocol" in corpo
    assert "NOMOS como servidor" in corpo and "nomos_status" in corpo
    assert "fs-local" in corpo                                 # server confiável


def test_secao_conversas_nao_vaza_corpo_das_mensagens(nomos_home):
    from nomos.conversations.store import ConversationStore
    ctx = _ctx(nomos_home)
    cs = ConversationStore(nomos_home / "conversas.db")
    cid = cs.nova_conversa()
    cs.add_turno(cid, "user", "pergunta comum sobre configuração")   # vira título
    cs.add_turno(cid, "assistant", "CORPO-SECRETO-DA-RESPOSTA-42")   # corpo
    cs.close()
    corpo = render_html(dados_dashboard(ctx))
    assert 'id="conversas"' in corpo
    # o painel só lê títulos/metadados — o corpo das mensagens NUNCA é exibido
    assert "CORPO-SECRETO-DA-RESPOSTA-42" not in corpo


def test_titulo_de_conversa_e_redigido(nomos_home):
    from nomos.conversations.store import ConversationStore
    ctx = _ctx(nomos_home)
    chave = "sk-" + "K" * 30
    cs = ConversationStore(nomos_home / "conversas.db")
    cid = cs.nova_conversa()
    cs.add_turno(cid, "user", f"minha chave {chave} por favor")     # 1ª msg = título
    cs.close()
    corpo = render_html(dados_dashboard(ctx))
    assert chave not in corpo                                        # título redigido


def test_secao_agentes_lista_oficiais_com_risco(nomos_home):
    corpo = render_html(dados_dashboard(_ctx(nomos_home)))
    assert 'id="agentes"' in corpo
    # os agentes oficiais vêm no pacote; risco máx sempre visível
    assert "risco máx" in corpo or "nenhum agente" in corpo


# 4. badge de atenção quando há candidatas de memória a revisar
def test_badge_de_candidatas_na_nav(nomos_home):
    from nomos.cognition.memory import Memory
    ctx = _ctx(nomos_home)
    Memory(nomos_home / "memory.db").propor_candidata("um fato a revisar")
    corpo = render_html(dados_dashboard(ctx))
    assert 'class="badge"' in corpo


# 5. contrato preservado: nada de POST/execução na página (só leitura)
def test_painel_continua_read_only(nomos_home):
    corpo = render_html(dados_dashboard(_ctx(nomos_home)))
    assert "<form" not in corpo and "method=\"post\"" not in corpo.lower()
    assert "nunca executa nada" in corpo                       # promessa explícita
