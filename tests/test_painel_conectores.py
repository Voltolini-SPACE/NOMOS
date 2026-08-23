"""A página de conectores lê a FONTE CANÔNICA e mostra as DUAS travas.

Histórico que este teste guarda: a 1ª versão mantinha uma tabela escrita à mão
em paralelo ao manifesto. Ela divergiu em tudo que importava — ids (`telegram`
vs `telegram-bot`), obrigatórias (SMTP e Signal) — e omitia o estado de
CONFIANÇA, que é justamente o que faz `nomos entrada` recusar. O dono seguiu os
passos da página e bateu em `'calendario-ics' não é confiável`.
"""
from __future__ import annotations

import re

from nomos.interface import painel_web
from nomos.interface.painel_web import _secao_conectores


def _fake_diag(itens, confiaveis=0):
    return {"raiz": "/x", "conectores": itens, "confiaveis": confiaveis,
            "revogados": []}


def _item(nome, *, status="experimental", env=(), faltando=None, nivel="A3"):
    faltando = list(env) if faltando is None else faltando
    return {"nome": nome, "dir": nome.split("-")[0],
            "status": status, "nivel": nivel, "nivel_padrao": nivel,
            "env": list(env), "env_faltando": faltando,
            "credenciais_ok": not faltando, "descricao": "d",
            "interpretador": "python3", "interpretador_ok": True}


def _chips(html):
    return dict(re.findall(
        r'id="conector-([a-z0-9-]+)".*?<span class="chip[^"]*">([^<]+)</span>',
        html, re.S))


def _patch(monkeypatch, itens, confiaveis=0):
    from nomos.interface import mcp_catalogo
    monkeypatch.setattr(mcp_catalogo, "diagnostico_conectores",
                        lambda *a, **k: _fake_diag(itens, confiaveis))


def test_usa_o_id_canonico_do_manifesto(monkeypatch):
    _patch(monkeypatch, [_item("calendario-ics", env=["NOMOS_ICS_PATH"])])
    html = _secao_conectores({})
    assert "conector-calendario-ics" in html
    assert 'id="conector-calendario"' not in html   # o id errado da 1ª versão


def test_credencial_ok_mas_SEM_confianca_nao_e_pronto(monkeypatch):
    """A trava que derrubou o dono: credencial presente e ainda assim recusado."""
    _patch(monkeypatch, [_item("calendario-ics", env=["NOMOS_ICS_PATH"],
                               faltando=[], status="experimental")])
    html = _secao_conectores({})
    assert _chips(html)["calendario-ics"] == "INCOMPLETO"
    assert "não confiável" in html


def test_confianca_e_credencial_juntas_viram_pronto(monkeypatch):
    _patch(monkeypatch, [_item("calendario-ics", env=["NOMOS_ICS_PATH"],
                               faltando=[], status="confiavel")], confiaveis=1)
    assert _chips(_secao_conectores({}))["calendario-ics"] == "PRONTO"


def test_revogado_tem_chip_proprio(monkeypatch):
    _patch(monkeypatch, [_item("slack-webhook", status="revogado")])
    assert _chips(_secao_conectores({}))["slack-webhook"] == "REVOGADO"


def test_confiar_usa_o_DIRETORIO_e_nao_o_nome_do_manifesto(monkeypatch):
    """`confiar calendario-ics` falha com "não achei" — medido no CLI real.

    O comando resolve por diretório. Mostrar o nome do manifesto no passo
    manda o dono direto para o erro, que foi o que aconteceu.
    """
    _patch(monkeypatch, [_item("calendario-ics", env=["NOMOS_ICS_PATH"])])
    html = _secao_conectores({})
    assert "nomos mcp confiar calendario" in html
    assert "nomos mcp confiar calendario-ics" not in html


def test_passo_de_confiar_vem_primeiro(monkeypatch):
    _patch(monkeypatch, [_item("telegram-bot", env=["NOMOS_TELEGRAM_TOKEN"])])
    html = _secao_conectores({})
    i_conf = html.index("nomos mcp confiar")
    i_export = html.index("NOMOS_TELEGRAM_TOKEN=", i_conf) if \
        "NOMOS_TELEGRAM_TOKEN=" in html else len(html)
    assert i_conf < i_export, "confiar tem de vir antes de exportar"


def test_catalogo_indisponivel_nao_derruba_o_painel(monkeypatch):
    from nomos.interface import mcp_catalogo

    def explode(*a, **k):
        raise RuntimeError("catálogo fora")
    monkeypatch.setattr(mcp_catalogo, "diagnostico_conectores", explode)
    html = _secao_conectores({})
    assert "nomos mcp doutor" in html          # degrada com saída útil
    assert "RuntimeError" in html


def test_diz_as_duas_travas_e_a_pegadinha_do_launchd(monkeypatch):
    _patch(monkeypatch, [_item("telegram-bot")])
    html = _secao_conectores({})
    assert "Duas travas" in html
    assert "não há campo de colar token" in html
    assert "não herda" in html
