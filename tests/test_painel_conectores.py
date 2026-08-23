"""A página de conectores do painel diz a VERDADE sobre o ambiente.

O valor desta página não é listar sete nomes — é dizer, por conector, se a
credencial está de fato presente. Um card que dissesse "PRONTO" sem medir
seria pior que nenhum card: mandaria o dono procurar defeito no lugar errado.
"""
from __future__ import annotations

import re

import pytest

from nomos.interface.painel_web import _CONECTORES, _secao_conectores

TODOS = {c[0] for c in _CONECTORES}


def _estados(html: str) -> dict[str, str]:
    return dict(re.findall(
        r'id="conector-([a-z-]+)".*?<span class="chip[^"]*">([^<]+)</span>',
        html, re.S))


@pytest.fixture
def ambiente_limpo(monkeypatch):
    for _cid, _i, _r, _s, _o, envs, _p in _CONECTORES:
        for var, _obrig in envs:
            monkeypatch.delenv(var, raising=False)


def test_lista_todos_os_conectores(ambiente_limpo):
    estados = _estados(_secao_conectores({}))
    assert set(estados) == TODOS
    assert len(TODOS) == 7


def test_sem_credencial_nenhum_diz_pronto(ambiente_limpo):
    assert set(_estados(_secao_conectores({})).values()) == {"NÃO CONFIGURADO"}


def test_credencial_completa_vira_pronto(ambiente_limpo, monkeypatch):
    monkeypatch.setenv("NOMOS_ICS_PATH", "/tmp/agenda.ics")
    assert _estados(_secao_conectores({}))["calendario"] == "PRONTO"


def test_credencial_parcial_vira_incompleto(ambiente_limpo, monkeypatch):
    """1 de 3 obrigatórias: nem PRONTO (mentira) nem NÃO CONFIGURADO (esconde)."""
    monkeypatch.setenv("NOMOS_IMAP_HOST", "imap.exemplo.com")
    assert _estados(_secao_conectores({}))["email-imap"] == "INCOMPLETO"


def test_variavel_opcional_sozinha_nao_promove(ambiente_limpo, monkeypatch):
    """`NOMOS_TELEGRAM_API` é opcional — não pode fingir que o bot está ligado."""
    monkeypatch.setenv("NOMOS_TELEGRAM_API", "https://api.telegram.org")
    assert _estados(_secao_conectores({}))["telegram"] == "INCOMPLETO"


def test_diz_que_nao_ha_campo_de_token(ambiente_limpo):
    """A honestidade central: o conector lê do AMBIENTE, não do cofre."""
    html = _secao_conectores({})
    assert "não existe campo de colar token" in html
    assert "não herda" in html          # a pegadinha do launchd


def test_toda_env_obrigatoria_aparece_na_ficha(ambiente_limpo):
    html = _secao_conectores({})
    for _cid, _i, _r, _s, _o, envs, _p in _CONECTORES:
        for var, obrig in envs:
            if obrig:
                assert var in html, var
