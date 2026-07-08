"""Conector MCP nomos↔Telegram (MC40) — governado, honesto, sem rede nos testes.

Contratos:
- servidor fala o dialeto MCP do repo (initialize/tools/list/tools/call)
  sobre stdio, em PROCESSO REAL (subprocess) — sem tocar a rede;
- sem NOMOS_TELEGRAM_TOKEN: initialize/list funcionam, chamadas falham
  FECHADO com instrução (nunca finge);
- com API mockada: enviar/quem_sou/atualizacoes retornam o contrato;
- o token JAMAIS aparece em erros (redação ativa);
- manifesto: válido para carregar_manifesto, todas as tools A3
  (credencial+rede), e o trust store aceita confiar/reconhecer;
- limites oficiais respeitados (texto ≤ 4096; limite de updates 1..20).
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
SERVIDOR = RAIZ / "examples" / "mcp" / "telegram" / "servidor.py"
MANIFESTO = RAIZ / "examples" / "mcp" / "telegram" / "manifesto.json"


def _carrega_modulo():
    import importlib.util
    spec = importlib.util.spec_from_file_location("tg_srv", SERVIDOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _stdio(mensagens: list[dict], env_extra: dict | None = None) -> list[dict]:
    """Roda o servidor REAL via stdio e devolve as respostas (sem rede)."""
    import os
    env = dict(os.environ)
    env.pop("NOMOS_TELEGRAM_TOKEN", None)
    env.update(env_extra or {})
    entrada = "".join(json.dumps(m) + "\n" for m in mensagens)
    p = subprocess.run([sys.executable, str(SERVIDOR)], input=entrada,
                       capture_output=True, text=True, timeout=20, env=env)
    return [json.loads(ln) for ln in p.stdout.splitlines() if ln.strip()]


# ---------------------------------------------------------------------------
# 1. dialeto MCP em processo real
# ---------------------------------------------------------------------------
def test_initialize_e_tools_list_sem_token():
    r = _stdio([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ])
    assert r[0]["result"]["serverInfo"]["name"] == "nomos-telegram"
    assert r[0]["result"]["protocolVersion"] == "2024-11-05"
    nomes = [t["name"] for t in r[1]["result"]["tools"]]
    assert nomes == ["telegram_quem_sou", "telegram_enviar",
                     "telegram_atualizacoes"]


def test_sem_token_falha_fechado_com_instrucao():
    r = _stdio([{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                 "params": {"name": "telegram_quem_sou", "arguments": {}}}])
    erro = r[0]["error"]["message"]
    assert "NOMOS_TELEGRAM_TOKEN" in erro and "BotFather" in erro


def test_metodo_desconhecido_e_tool_desconhecida():
    r = _stdio([
        {"jsonrpc": "2.0", "id": 1, "method": "inexistente"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "hackear_tudo", "arguments": {}}},
    ])
    assert r[0]["error"]["code"] == -32601
    assert "desconhecida" in r[1]["error"]["message"]


# ---------------------------------------------------------------------------
# 2. tools com a API mockada (nenhum byte sai para a rede)
# ---------------------------------------------------------------------------
def test_enviar_e_quem_sou_com_api_mockada(monkeypatch):
    mod = _carrega_modulo()
    monkeypatch.setenv("NOMOS_TELEGRAM_TOKEN", "111:AAA-token-de-teste")
    chamadas = []

    def api_falsa(metodo, params):
        chamadas.append((metodo, params))
        if metodo == "getMe":
            return {"id": 7, "first_name": "Nomos", "username": "nomos_bot",
                    "can_join_groups": True}
        if metodo == "sendMessage":
            return {"message_id": 42, "chat": {"id": int(params["chat_id"])}}
        raise AssertionError(metodo)

    monkeypatch.setattr(mod, "chamar_api", api_falsa)
    quem = mod._rodar_tool("telegram_quem_sou", {})
    assert quem["usuario"] == "@nomos_bot"
    env = mod._rodar_tool("telegram_enviar",
                          {"chat_id": "123", "texto": "oi"})
    assert env == {"enviada": True, "message_id": 42, "chat_id": 123}
    assert chamadas[1][0] == "sendMessage"


def test_atualizacoes_com_offset_e_truncamento(monkeypatch):
    mod = _carrega_modulo()
    monkeypatch.setenv("NOMOS_TELEGRAM_TOKEN", "111:AAA")

    def api_falsa(metodo, params):
        assert metodo == "getUpdates" and params["limit"] == 20
        return [{"update_id": 10,
                 "message": {"from": {"first_name": "Ana"},
                             "chat": {"id": 5}, "date": 1,
                             "text": "x" * 900}}]

    monkeypatch.setattr(mod, "chamar_api", api_falsa)
    r = mod._rodar_tool("telegram_atualizacoes", {"limite": 99})
    assert r["next_offset"] == 11
    assert len(r["mensagens"][0]["texto"]) == 500     # truncado


def test_limites_oficiais(monkeypatch):
    mod = _carrega_modulo()
    monkeypatch.setenv("NOMOS_TELEGRAM_TOKEN", "111:AAA")
    monkeypatch.setattr(mod, "chamar_api",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("não deveria chamar")))
    with pytest.raises(ValueError, match="4096"):
        mod._rodar_tool("telegram_enviar",
                        {"chat_id": "1", "texto": "x" * 5000})
    with pytest.raises(ValueError, match="obrigat"):
        mod._rodar_tool("telegram_enviar", {"chat_id": "", "texto": "x"})


def test_token_jamais_vaza_em_erros(monkeypatch):
    mod = _carrega_modulo()
    token = "999:SEGREDO-QUE-NAO-PODE-APARECER"
    monkeypatch.setenv("NOMOS_TELEGRAM_TOKEN", token)

    def api_explode(metodo, params):
        raise RuntimeError(f"falha bruta com url .../bot{token}/getMe")

    monkeypatch.setattr(mod, "chamar_api", api_explode)
    resposta = mod._despachar({"jsonrpc": "2.0", "id": 1,
                               "method": "tools/call",
                               "params": {"name": "telegram_quem_sou",
                                          "arguments": {}}})
    assert token not in json.dumps(resposta)
    assert "***" in resposta["error"]["message"]


# ---------------------------------------------------------------------------
# 3. manifesto + trust store do NOMOS
# ---------------------------------------------------------------------------
def test_manifesto_valido_e_todas_tools_a3():
    from nomos.interface.mcp_client import carregar_manifesto, nivel_da_tool
    m = carregar_manifesto(MANIFESTO)
    assert m["nome"] == "telegram-bot"
    assert m["nivel_padrao"] == "A3"
    for t in ("telegram_quem_sou", "telegram_enviar",
              "telegram_atualizacoes"):
        assert nivel_da_tool(m, t) == "A3"
    # tool que não existe herda o padrão (A3) — nunca menos
    assert nivel_da_tool(m, "qualquer_outra") == "A3"


def test_cliente_mcp_do_nomos_conecta_de_verdade():
    """Integração REAL: o ClienteMCP do NOMOS sobe o servidor via stdio,
    faz o handshake e lista as tools — nenhum byte sai para a rede."""
    from nomos.interface.mcp_client import ClienteMCP, carregar_manifesto
    m = carregar_manifesto(MANIFESTO)
    with ClienteMCP(m, timeout=15, base=MANIFESTO.parent) as cli:
        tools = cli.tools()
    nomes = [t["name"] for t in tools]
    assert "telegram_enviar" in nomes and len(nomes) == 3
    # e o nível A3 vem anotado do manifesto, tool a tool
    assert all(t["nivel"] == "A3" for t in tools)


def test_trust_store_confia_e_reconhece(nomos_home):
    from nomos.interface import mcp_catalogo as cat
    from nomos.interface.mcp_client import carregar_manifesto
    nomos_home.mkdir(parents=True, exist_ok=True)
    m = carregar_manifesto(MANIFESTO)
    cat.confiar(nomos_home, m)
    listagem = cat.listar(nomos_home)
    nomes = [s["nome"] for s in listagem["confiaveis"]]
    assert "telegram-bot" in nomes
