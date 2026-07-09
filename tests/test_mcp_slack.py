"""Conector MCP nomos↔Slack (Fase 2) — envio por Incoming Webhook, sem rede.

Contratos:
- dialeto MCP em PROCESSO REAL (initialize/tools/list/tools/call) sobre stdio;
- sem NOMOS_SLACK_WEBHOOK: initialize/list funcionam, chamadas falham FECHADO;
- recusa destino fora de hooks.slack.com (não vira POST genérico);
- com urlopen MOCKADO: slack_enviar posta {"text": …} e confirma no "ok";
- a URL do webhook (secreta) JAMAIS vaza em erro; em quem_sou aparece mascarada;
- manifesto válido, todas as tools A3, ClienteMCP real conecta e lista.
"""
import io
import json
import os
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
SERVIDOR = RAIZ / "examples" / "mcp" / "slack" / "servidor.py"
MANIFESTO = RAIZ / "examples" / "mcp" / "slack" / "manifesto.json"

_WEBHOOK = "https://hooks.slack.com/services/T0ABCDEF/B0GHIJKL/supersecrettoken123"


def _carrega_modulo():
    import importlib.util
    spec = importlib.util.spec_from_file_location("slack_srv", SERVIDOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _stdio(mensagens, env_extra=None):
    env = dict(os.environ)
    env.pop("NOMOS_SLACK_WEBHOOK", None)
    env.update(env_extra or {})
    entrada = "".join(json.dumps(m) + "\n" for m in mensagens)
    p = subprocess.run([sys.executable, str(SERVIDOR)], input=entrada,
                       capture_output=True, text=True, timeout=20, env=env)
    return [json.loads(ln) for ln in p.stdout.splitlines() if ln.strip()]


class _FakeResp:
    def __init__(self, corpo=b"ok"):
        self._c = corpo

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._c


# 1. dialeto MCP em processo real ------------------------------------------
def test_dialeto_e_fail_closed_sem_webhook():
    r = _stdio([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "slack_enviar", "arguments": {"texto": "oi"}}},
    ])
    assert r[0]["result"]["serverInfo"]["name"] == "nomos-slack-webhook"
    assert [t["name"] for t in r[1]["result"]["tools"]] == [
        "slack_quem_sou", "slack_enviar"]
    assert "NOMOS_SLACK_WEBHOOK" in r[2]["error"]["message"]


def test_recusa_destino_fora_do_slack():
    r = _stdio([{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                 "params": {"name": "slack_quem_sou", "arguments": {}}}],
               env_extra={"NOMOS_SLACK_WEBHOOK": "http://evil.example.com/x"})
    assert "hooks.slack.com" in r[0]["error"]["message"]


# 2. tools com urlopen MOCKADO ---------------------------------------------
def test_quem_sou_mascara_o_webhook(monkeypatch):
    mod = _carrega_modulo()
    monkeypatch.setenv("NOMOS_SLACK_WEBHOOK", _WEBHOOK)
    r = mod._rodar_tool("slack_quem_sou", {})
    assert r["webhook"].startswith("hooks.slack.com/services/T0A***")
    assert "supersecrettoken123" not in json.dumps(r)     # segredo não aparece


def test_envio_posta_texto_e_confirma_ok(monkeypatch):
    mod = _carrega_modulo()
    monkeypatch.setenv("NOMOS_SLACK_WEBHOOK", _WEBHOOK)
    capturado = {}

    def fake_urlopen(req, timeout=None):
        capturado["url"] = req.full_url
        capturado["data"] = req.data
        return _FakeResp(b"ok")

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    r = mod._rodar_tool("slack_enviar", {"texto": "deploy verde ✅"})
    assert r["enviada"] is True
    assert capturado["url"].startswith("https://hooks.slack.com/")
    assert json.loads(capturado["data"])["text"] == "deploy verde ✅"


def test_texto_vazio_recusa(monkeypatch):
    mod = _carrega_modulo()
    monkeypatch.setenv("NOMOS_SLACK_WEBHOOK", _WEBHOOK)
    with pytest.raises(ValueError):
        mod._rodar_tool("slack_enviar", {"texto": "   "})


def test_slack_nao_confirma_vira_erro(monkeypatch):
    """Slack devolve algo != 'ok' ⇒ erro honesto, não finge que enviou."""
    mod = _carrega_modulo()
    monkeypatch.setenv("NOMOS_SLACK_WEBHOOK", _WEBHOOK)
    monkeypatch.setattr(mod.urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResp(b"invalid_payload"))
    with pytest.raises(RuntimeError):
        mod._rodar_tool("slack_enviar", {"texto": "oi"})


def test_webhook_redigido_em_erro_http(monkeypatch):
    """Se o corpo do erro ecoar a URL, a redação troca por *** (defesa extra)."""
    mod = _carrega_modulo()
    seg = "https://hooks.slack.com/services/T/B/SEGREDO-NAO-PODE-VAZAR"
    monkeypatch.setenv("NOMOS_SLACK_WEBHOOK", seg)

    def explode(req, timeout=None):
        raise urllib.error.HTTPError(seg, 500, "erro", {}, io.BytesIO(seg.encode()))

    monkeypatch.setattr(mod.urllib.request, "urlopen", explode)
    resp = mod._despachar({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": "slack_enviar",
                                      "arguments": {"texto": "oi"}}})
    assert seg not in json.dumps(resp)                    # a URL secreta não vaza
    assert "***" in resp["error"]["message"]


def test_webhook_nao_vaza_em_erro_generico(monkeypatch):
    mod = _carrega_modulo()
    seg = "https://hooks.slack.com/services/T/B/OUTRO-SEGREDO"
    monkeypatch.setenv("NOMOS_SLACK_WEBHOOK", seg)

    def explode(req, timeout=None):
        raise urllib.error.URLError(f"falhou com {seg}")

    monkeypatch.setattr(mod.urllib.request, "urlopen", explode)
    resp = mod._despachar({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": "slack_enviar",
                                      "arguments": {"texto": "oi"}}})
    assert seg not in json.dumps(resp)                    # nunca vaza o segredo


# 3. manifesto + trust + ClienteMCP real ------------------------------------
def test_manifesto_valido_e_todas_tools_a3():
    from nomos.interface.mcp_client import carregar_manifesto, nivel_da_tool
    m = carregar_manifesto(MANIFESTO)
    assert m["nome"] == "slack-webhook"
    for t in ("slack_quem_sou", "slack_enviar"):
        assert nivel_da_tool(m, t) == "A3"
    assert nivel_da_tool(m, "qualquer") == "A3"


def test_cliente_mcp_conecta_e_lista():
    from nomos.interface.mcp_client import ClienteMCP, carregar_manifesto
    m = carregar_manifesto(MANIFESTO)
    with ClienteMCP(m, timeout=15, base=MANIFESTO.parent) as cli:
        nomes = [t["name"] for t in cli.tools()]
    assert nomes == ["slack_quem_sou", "slack_enviar"]
