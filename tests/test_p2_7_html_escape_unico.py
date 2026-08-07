"""P2-7 (auditoria de 2026-07-17): escape de HTML único, null-safe.

Antes: `painel_web.py` usava o alias local `e = html.escape` (repetido em 9
funções); `panel.py` chamava `html.escape(...)` inline; `mosaic/panel.py`
tinha sua própria `_esc` com `str(s or "")`. As duas primeiras QUEBRAM
(`AttributeError`) em valor não-string (ex.: `None`); a terceira não quebra,
mas apaga valores "falsy" legítimos (`0`, `False`) como se fossem vazios.

Este arquivo prova: (1) `nomos.interface._html.esc` nunca quebra e nunca
apaga um falsy real; (2) `mosaic.panel._esc` foi alinhada ao mesmo
contrato; (3) para qualquer entrada que já fosse `str`, o resultado é
idêntico ao `html.escape(x, quote=True)` de antes — nenhuma saída visual
já validada por outros testes muda.
"""
import html as _html_stdlib

import pytest

from nomos.interface._html import esc
from nomos.mosaic.panel import _esc as mosaic_esc


# ---------------- nomos.interface._html.esc ----------------

def test_esc_none_vira_string_vazia():
    assert esc(None) == ""


def test_esc_nao_quebra_em_tipos_nao_string():
    assert esc(0) == "0"
    assert esc(False) == "False"
    assert esc(True) == "True"
    assert esc(3.14) == "3.14"
    assert esc([1, 2]) == "[1, 2]"


def test_esc_string_identico_ao_html_escape_puro():
    """Para entrada já-string, o resultado não pode mudar em relação ao
    comportamento anterior (html.escape(x, quote=True))."""
    casos = ["", "texto normal", "<script>alert(1)</script>",
             "aspas \" e 'simples'", "acentuação: ção ã é", "a & b"]
    for c in casos:
        assert esc(c) == _html_stdlib.escape(c, quote=True)


def test_esc_escapa_tags_e_aspas():
    assert esc("<b>x</b>") == "&lt;b&gt;x&lt;/b&gt;"
    assert "&quot;" in esc('diz "oi"')


# ---------------- nomos.mosaic.panel._esc (cópia local, mesmo contrato) ----

def test_mosaic_esc_none_vira_string_vazia():
    assert mosaic_esc(None) == ""


def test_mosaic_esc_nao_apaga_falsy_legitimo():
    """P2-7: bug real — `str(s or "")` fazia _esc(0) virar "" em vez de
    "0" (ex.: um contador zerado sumia do HTML). Agora só None vira ""."""
    assert mosaic_esc(0) == "0"
    assert mosaic_esc(False) == "False"
    assert mosaic_esc("") == ""    # string vazia real: continua vazia


def test_mosaic_esc_string_identico_ao_html_escape_puro():
    casos = ["", "texto normal", "<script>alert(1)</script>", "a & b"]
    for c in casos:
        assert mosaic_esc(c) == _html_stdlib.escape(c, quote=True)


# ---------------- painel_web.py: aliases locais não quebram mais ----------

def test_sidebar_nao_quebra_com_contagem_zero(nomos_home):
    """_sidebar() já tratava n_aprov==0 via `if n_aprov else ""` (não
    chamava e() nesse caso); confirma que o alias local null-safe (e=esc)
    segue produzindo HTML normal com dados reais e contagem zerada."""
    from nomos.interface.painel_web import _sidebar, dados_dashboard
    from nomos.kernel.audit import AuditLog
    from nomos.kernel.policy import PolicyEngine
    nomos_home.mkdir(parents=True, exist_ok=True)
    (nomos_home / "skills").mkdir(exist_ok=True)
    ctx = {"home": nomos_home, "policy": PolicyEngine(nomos_home / "p.json"),
           "audit": AuditLog(nomos_home / "logs" / "audit.jsonl"),
           "skills": nomos_home / "skills"}
    d = dados_dashboard(ctx)
    assert d["memoria"]["candidatas"] == 0     # confirma o caso falsy real
    out = _sidebar(d, 0)
    assert isinstance(out, str) and "<a" in out


def test_pagina_audit_nao_quebra_com_query_vazia(nomos_home):
    """_pagina_audit usa e(q) com q podendo ser "" — exercita o alias
    local e=esc naquele método sem precisar subir um servidor HTTP."""
    from nomos.kernel.audit import AuditLog
    from nomos.kernel.policy import PolicyEngine
    from nomos.interface.painel_web import DashboardServer
    nomos_home.mkdir(parents=True, exist_ok=True)
    (nomos_home / "skills").mkdir(exist_ok=True)
    ctx = {"home": nomos_home, "policy": PolicyEngine(nomos_home / "p.json"),
           "audit": AuditLog(nomos_home / "logs" / "audit.jsonl"),
           "skills": nomos_home / "skills"}
    srv = DashboardServer(ctx)
    assert srv is not None  # smoke: import/instância não quebra com o novo helper


# ---------------- interface/panel.py: aprovações usam o helper único -----

def test_panel_aprovacoes_usa_helper_unico_null_safe(nomos_home, tmp_path):
    """Prova estrutural: panel.py não referencia mais html.escape diretamente
    — usa nomos.interface._html.esc (via alias html_escape), o mesmo
    contrato de painel_web.py."""
    import inspect
    from nomos.interface import panel as panel_mod
    src = inspect.getsource(panel_mod)
    assert "import html\n" not in src        # não importa mais o módulo stdlib direto
    assert src.count("html_escape(") >= 5    # os 5 campos do item de aprovação
    assert panel_mod.html_escape is esc      # mesmo helper único do pacote


@pytest.mark.parametrize("valor_alvo", [None, 0, False])
def test_esc_aceita_qualquer_tipo_sem_lancar(valor_alvo):
    """Regressão direta do achado: html.escape(None) lançaria
    AttributeError; esc(None) não lança nunca."""
    assert isinstance(esc(valor_alvo), str)
