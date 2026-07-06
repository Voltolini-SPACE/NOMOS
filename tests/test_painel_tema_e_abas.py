"""MC37 — painel em ABAS (menos densidade) + TEMA claro/escuro.

Contratos:
- 5 abas (data-aba) e só a "visão geral" nasce ativa;
- deep-link de seção antiga (#motores…) continua no HTML (âncora + subnav),
  então links salvos não quebram;
- tema: escuro é o padrão (brandbook); há bloco de variáveis do tema claro,
  respeito a prefers-color-scheme, botão de alternância e boot sem flash;
- a página continua read-only sem fila (nenhum <form>).
"""
import re

import pytest

from nomos.cognition import motores
from nomos.interface.painel_web import dados_dashboard, render_html
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import PolicyEngine


@pytest.fixture(autouse=True)
def _iso(nomos_home, monkeypatch):
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: [])
    monkeypatch.setattr(motores, "_http_ok", lambda *a, **k: False)
    monkeypatch.setattr("shutil.which", lambda *a, **k: None)
    motores.limpar_cache()
    yield
    motores.limpar_cache()


def _ctx(home):
    home.mkdir(parents=True, exist_ok=True)
    (home / "skills").mkdir(exist_ok=True)
    return {"home": home, "policy": PolicyEngine(home / "policy.json"),
            "audit": AuditLog(home / "logs" / "audit.jsonl"),
            "skills": home / "skills"}


def _html(home):
    return render_html(dados_dashboard(_ctx(home)))


# ---------------------------------------------------------------- abas
def test_seis_abas_e_so_visao_ativa(nomos_home):
    # MC38: entrou a aba "chat" (estilo ChatGPT) — 6 abas agora
    corpo = _html(nomos_home)
    for aba in ("visao", "chat", "cerebro", "capacidades", "operacao", "ajuda"):
        assert f'data-aba="{aba}"' in corpo, f"aba {aba} ausente"
    # a sidebar (link) e a seção (section) — 2 ocorrências por aba
    assert corpo.count('data-aba="chat"') >= 2
    # só a visão geral começa aberta (ativa)
    ativas = re.findall(r'class="aba ativa" data-aba="(\w+)"', corpo)
    assert ativas == ["visao"], f"deveria abrir só na visão geral, veio {ativas}"


def test_deep_links_de_secoes_antigas_preservados(nomos_home):
    corpo = _html(nomos_home)
    # âncoras que existiam na página única continuam válidas (id + link na subnav)
    for anc in ("status", "aprovacoes", "checkup", "motores", "conversas",
                "memoria", "skills", "agentes", "capacidades", "mcp",
                "rotinas", "evidencias", "politica", "auditoria", "sistema",
                "ajuda"):
        assert f'id="{anc}"' in corpo, f"seção {anc} perdeu a âncora"
        assert f'href="#{anc}"' in corpo, f"nada linka #{anc} (subnav?)"


def test_menos_kpis_visiveis(nomos_home):
    # densidade: a faixa de KPIs caiu de 8 para 5
    corpo = _html(nomos_home)
    assert corpo.count('<div class="kpi">') == 5


# ---------------------------------------------------------------- tema
def test_tema_escuro_e_claro_ambos_definidos(nomos_home):
    corpo = _html(nomos_home)
    # escuro é o padrão (marca congelada)
    assert "--neon:#5AF78E" in corpo
    # existe um tema claro explícito e o respeito ao SO
    assert ':root[data-tema="claro"]' in corpo
    assert "prefers-color-scheme:light" in corpo
    # o claro redefine o fundo para um tom claro (não é o mesmo do escuro)
    assert "#f4f7f4" in corpo


def test_botao_de_tema_e_boot_sem_flash(nomos_home):
    corpo = _html(nomos_home)
    assert 'id="tema-btn"' in corpo                 # alternância acessível
    assert 'aria-pressed' in corpo
    # boot lê a preferência salva ANTES do <style> (evita flash de tema)
    idx_boot = corpo.find("localStorage.getItem('nomos-tema')")
    idx_style = corpo.find("<style>")
    assert 0 < idx_boot < idx_style, "boot do tema deve vir antes do <style>"


def test_sem_fila_continua_read_only(nomos_home):
    corpo = _html(nomos_home)
    assert "<form" not in corpo and 'method="post"' not in corpo.lower()
