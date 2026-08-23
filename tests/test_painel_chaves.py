"""A aba de chaves grava no cofre SEM vazar o valor.

Propriedades provadas fim a fim (servidor de verdade em 127.0.0.1):
- POST /chaves/gravar com token+passphrase+valor grava no cofre cifrado;
- o valor NUNCA aparece na resposta, na URL de redirect nem na página seguinte;
- a auditoria registra só o NOME (via=painel), nunca o valor;
- token errado é recusado (403); passphrase errada é recusada (403);
- a listagem mostra só nomes.
"""
from __future__ import annotations

import urllib.request
from pathlib import Path

import pytest

from nomos.interface import painel_web as pw
from nomos.interface.painel_web import DashboardServer as Painel
from nomos.kernel.audit import AuditLog
from nomos.kernel.vault import Vault

VALOR = "sk-SEGREDO-que-nao-pode-vazar-1234567890"
SENHA = "senha-do-cofre-forte"


@pytest.fixture
def painel(tmp_path):
    (tmp_path).mkdir(exist_ok=True)
    Vault(tmp_path / "vault.json").init(SENHA)          # cofre pronto
    ctx = {"home": tmp_path, "audit": AuditLog(tmp_path / "audit.jsonl")}
    p = Painel(ctx, port=0, fila_aprovacoes=False)
    p.start()
    yield p
    p._server.shutdown()


def _post(url, campos):
    from urllib.parse import urlencode
    req = urllib.request.Request(url, data=urlencode(campos).encode(),
                                 method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        r = urllib.request.urlopen(req)
        return r.status, r.geturl(), r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.url, e.read().decode()


def _base(p):
    return f"http://127.0.0.1:{p.port}/d/{p.secret}"


def test_grava_e_nao_vaza(painel):
    base = _base(painel)
    status, url_final, corpo = _post(base + "/chaves/gravar",
                                     {"token": painel.chaves_token,
                                      "nome": "groq_api_key",
                                      "passphrase": SENHA, "valor": VALOR})
    # gravou: cofre tem a entrada, com o valor certo
    v = Vault(Path(painel.ctx["home"]) / "vault.json")
    assert v.get("groq_api_key", SENHA) == VALOR
    # NÃO vazou: nem na URL de redirect, nem no corpo, nem na página seguinte
    assert VALOR not in url_final
    assert VALOR not in corpo
    pag = urllib.request.urlopen(base + "/?chave_gravada=groq_api_key").read().decode()
    assert VALOR not in pag
    assert "groq_api_key" in pag           # o NOME aparece, o valor não


def test_auditoria_so_o_nome(painel):
    base = _base(painel)
    _post(base + "/chaves/gravar", {"token": painel.chaves_token,
                                    "nome": "mistral_api_key",
                                    "passphrase": SENHA, "valor": VALOR})
    linhas = (Path(painel.ctx["home"]) / "audit.jsonl").read_text()
    assert "vault.set" in linhas
    assert "mistral_api_key" in linhas     # o nome, sim
    assert VALOR not in linhas             # o valor, JAMAIS


def test_token_errado_recusa(painel):
    base = _base(painel)
    status, _, _ = _post(base + "/chaves/gravar",
                         {"token": "token-falso", "nome": "x_api_key",
                          "passphrase": SENHA, "valor": VALOR})
    assert status == 403
    assert Vault(Path(painel.ctx["home"]) / "vault.json").names() == []


def test_passphrase_errada_recusa_sem_vazar(painel):
    base = _base(painel)
    status, _, corpo = _post(base + "/chaves/gravar",
                             {"token": painel.chaves_token, "nome": "y_api_key",
                              "passphrase": "senha-ERRADA", "valor": VALOR})
    assert status == 403
    assert VALOR not in corpo
    assert "y_api_key" not in Vault(Path(painel.ctx["home"]) / "vault.json").names()


def test_nome_invalido_recusa(painel):
    base = _base(painel)
    for ruim in ("com espaço", "MAIÚSCULA", "a", "../escape", "x;drop"):
        status, _, _ = _post(base + "/chaves/gravar",
                             {"token": painel.chaves_token, "nome": ruim,
                              "passphrase": SENHA, "valor": VALOR})
        assert status == 400, f"nome ruim aceito: {ruim!r}"


def test_get_form_nao_expoe_valor_nem_token_no_html_de_leitura(painel):
    """A aba renderiza sem quebrar e não embute valor de chave nenhuma."""
    base = _base(painel)
    _post(base + "/chaves/gravar", {"token": painel.chaves_token,
                                    "nome": "omniroute_api_key",
                                    "passphrase": SENHA, "valor": VALOR})
    pag = urllib.request.urlopen(base + "/#chaves").read().decode()
    assert "omniroute_api_key" in pag
    assert VALOR not in pag


def test_aba_traz_links_das_fontes_gratuitas(painel):
    """A aba mostra onde conseguir cada chave, com link e nome sugerido."""
    base = _base(painel)
    pag = urllib.request.urlopen(base + "/#chaves").read().decode()
    # os 4 provedores gratuitos, com URL clicável em nova aba protegida
    for host in ("console.groq.com", "aistudio.google.com",
                 "openrouter.ai", "console.mistral.ai"):
        assert host in pag, f"falta o link de {host}"
    assert 'rel="noopener noreferrer"' in pag       # não vaza a origem
    assert "Não cole a chave em chat" in pag        # a advertência de segurança
    # o nome sugerido aparece para orientar o campo
    assert "groq_api_key" in pag


# --------------------------------------------------------------------------
# A página não pode prometer o que o código não cumpre
# --------------------------------------------------------------------------
def test_pagina_declara_o_que_o_nomos_realmente_le():
    """Medido: os únicos nomes passados a vault.get() em src/nomos são
    omniroute_api_key, anthropic_api_key e __audit_hmac_key__. A página
    oferecia 4 chaves gratuitas que NENHUMA linha lê — e não oferecia a de
    nuvem que é lida. Convite a colar chave que não liga nada."""
    html = pw._secao_chaves({}, {"token": "T", "base": "/d/x", "nomes": []})
    assert "O que o NOMOS lê hoje" in html
    assert "omniroute_api_key" in html
    assert "anthropic_api_key" in html
    # e diz, sem rodeio, que as outras não são lidas
    assert "nenhuma parte do NOMOS o lê" in html
    assert "OmniRoute" in html


def test_fontes_gratuitas_nao_prometem_ligar_sozinhas():
    html = pw._secao_chaves({}, {"token": "T", "base": "/d/x", "nomes": []})
    assert "quem roteia é o OmniRoute" in html
    # a frase antiga dizia só "volte para colar aqui", sugerindo que bastava
    assert "volte para colar aqui" not in html


def test_o_conjunto_lido_bate_com_o_codigo():
    """Se alguém passar a ler uma chave nova (ou parar de ler uma), este teste
    quebra e a página tem de ser atualizada junto."""
    import re
    from pathlib import Path
    raiz = Path(pw.__file__).resolve().parents[1]
    nomes: set[str] = set()
    for f in raiz.rglob("*.py"):
        for m in re.finditer(r"vault\.get\(\s*([A-Za-z_][\w.]*)", f.read_text()):
            nomes.add(m.group(1).split(".")[-1])
    assert nomes <= {"CLOUD_KEY_NAME", "RELAY_KEY_NAME", "CHAVE_COFRE"}, (
        f"chave nova sendo lida: {nomes} — atualize a aba Chaves")
