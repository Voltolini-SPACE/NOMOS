"""Conector MCP nomos↔WhatsApp Cloud (MC40) — oficial, só envio, honesto.

Mesmos contratos do conector Telegram: dialeto MCP em processo real (sem
rede), fail-closed sem credenciais, API mockada para o contrato de envio,
token jamais em erros, manifesto A3 válido no trust store.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
SERVIDOR = RAIZ / "examples" / "mcp" / "whatsapp-cloud" / "servidor.py"
MANIFESTO = RAIZ / "examples" / "mcp" / "whatsapp-cloud" / "manifesto.json"


def _carrega_modulo():
    import importlib.util
    spec = importlib.util.spec_from_file_location("wa_srv", SERVIDOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _stdio(mensagens: list[dict]) -> list[dict]:
    import os
    env = dict(os.environ)
    env.pop("NOMOS_WHATSAPP_TOKEN", None)
    env.pop("NOMOS_WHATSAPP_PHONE_ID", None)
    entrada = "".join(json.dumps(m) + "\n" for m in mensagens)
    p = subprocess.run([sys.executable, str(SERVIDOR)], input=entrada,
                       capture_output=True, text=True, timeout=20, env=env)
    return [json.loads(ln) for ln in p.stdout.splitlines() if ln.strip()]


def test_dialeto_e_fail_closed_sem_credenciais():
    r = _stdio([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "whatsapp_enviar_texto",
                    "arguments": {"numero": "5511999998888", "texto": "oi"}}},
    ])
    assert r[0]["result"]["serverInfo"]["name"] == "nomos-whatsapp-cloud"
    assert [t["name"] for t in r[1]["result"]["tools"]] == [
        "whatsapp_enviar_texto", "whatsapp_enviar_template"]
    erro = r[2]["error"]["message"]
    assert "NOMOS_WHATSAPP_TOKEN" in erro and "PHONE_ID" in erro


def test_envio_texto_e_template_com_api_mockada(monkeypatch):
    mod = _carrega_modulo()
    monkeypatch.setenv("NOMOS_WHATSAPP_TOKEN", "EAAG-teste")
    monkeypatch.setenv("NOMOS_WHATSAPP_PHONE_ID", "111222333")
    payloads = []

    def api_falsa(payload):
        payloads.append(payload)
        return {"messages": [{"id": "wamid.XYZ"}]}

    monkeypatch.setattr(mod, "chamar_api", api_falsa)
    r1 = mod._rodar_tool("whatsapp_enviar_texto",
                         {"numero": "+5511999998888", "texto": "olá"})
    assert r1 == {"enviada": True, "message_id": "wamid.XYZ"}
    assert payloads[0]["to"] == "5511999998888"      # + removido
    assert payloads[0]["type"] == "text"
    r2 = mod._rodar_tool("whatsapp_enviar_template",
                         {"numero": "5511999998888",
                          "template": "hello_world", "idioma": "en_US"})
    assert r2["template"] == "hello_world"
    assert payloads[1]["template"]["language"]["code"] == "en_US"


def test_validacoes_de_numero_e_texto(monkeypatch):
    mod = _carrega_modulo()
    monkeypatch.setenv("NOMOS_WHATSAPP_TOKEN", "t")
    monkeypatch.setenv("NOMOS_WHATSAPP_PHONE_ID", "p")
    monkeypatch.setattr(mod, "chamar_api",
                        lambda *a: (_ for _ in ()).throw(AssertionError))
    with pytest.raises(ValueError, match="internacional"):
        mod._rodar_tool("whatsapp_enviar_texto",
                        {"numero": "abc", "texto": "x"})
    with pytest.raises(ValueError, match="4096"):
        mod._rodar_tool("whatsapp_enviar_texto",
                        {"numero": "5511999998888", "texto": "x" * 5000})


def test_token_jamais_vaza(monkeypatch):
    mod = _carrega_modulo()
    token = "EAAG-SEGREDO-NAO-VAZA"
    monkeypatch.setenv("NOMOS_WHATSAPP_TOKEN", token)
    monkeypatch.setenv("NOMOS_WHATSAPP_PHONE_ID", "1")
    monkeypatch.setattr(mod, "chamar_api", lambda p: (_ for _ in ()).throw(
        RuntimeError(f"explodiu com Bearer {token}")))
    resp = mod._despachar({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": "whatsapp_enviar_texto",
                                      "arguments": {"numero": "5511999998888",
                                                    "texto": "x"}}})
    assert token not in json.dumps(resp)


def test_manifesto_a3_e_trust_store(nomos_home):
    from nomos.interface import mcp_catalogo as cat
    from nomos.interface.mcp_client import carregar_manifesto, nivel_da_tool
    m = carregar_manifesto(MANIFESTO)
    assert m["nivel_padrao"] == "A3"
    assert nivel_da_tool(m, "whatsapp_enviar_texto") == "A3"
    nomos_home.mkdir(parents=True, exist_ok=True)
    cat.confiar(nomos_home, m)
    assert "whatsapp-cloud" in [s["nome"] for s in
                                cat.listar(nomos_home)["confiaveis"]]
