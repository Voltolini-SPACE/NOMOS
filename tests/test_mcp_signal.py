"""Conector MCP nomos↔Signal (MC49) — via signal-cli local, sem rede nos testes.

Contratos (espelham os outros conectores):
- servidor fala o dialeto MCP do repo (initialize/tools/list/tools/call) sobre
  stdio, em PROCESSO REAL (subprocess) — sem tocar rede nem signal-cli real;
- sem NOMOS_SIGNAL_NUMBER ou sem signal-cli: initialize/list funcionam, chamadas
  falham FECHADO com instrução (nunca finge);
- com o signal-cli MOCKADO: enviar/quem_sou retornam o contrato; o número da
  conta aparece só MASCARADO e JAMAIS vaza em erros (redação ativa);
- manifesto válido, todas as tools A3, e o trust store confia/reconhece.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SERVIDOR = RAIZ / "examples" / "mcp" / "signal" / "servidor.py"
MANIFESTO = RAIZ / "examples" / "mcp" / "signal" / "manifesto.json"


def _carrega_modulo():
    import importlib.util
    spec = importlib.util.spec_from_file_location("sig_srv", SERVIDOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _stdio(mensagens, env_extra=None):
    env = dict(os.environ)
    env.pop("NOMOS_SIGNAL_NUMBER", None)
    env.update(env_extra or {})
    entrada = "".join(json.dumps(m) + "\n" for m in mensagens)
    p = subprocess.run([sys.executable, str(SERVIDOR)], input=entrada,
                       capture_output=True, text=True, timeout=20, env=env)
    return [json.loads(ln) for ln in p.stdout.splitlines() if ln.strip()]


# 1. dialeto MCP em processo real ------------------------------------------
def test_initialize_e_tools_list():
    r = _stdio([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ])
    assert r[0]["result"]["serverInfo"]["name"] == "nomos-signal"
    assert r[0]["result"]["protocolVersion"] == "2024-11-05"
    nomes = [t["name"] for t in r[1]["result"]["tools"]]
    assert nomes == ["signal_quem_sou", "signal_enviar"]


def test_sem_numero_falha_fechado():
    r = _stdio([{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                 "params": {"name": "signal_quem_sou", "arguments": {}}}])
    assert "NOMOS_SIGNAL_NUMBER" in r[0]["error"]["message"]


def test_sem_signalcli_falha_fechado():
    # com número setado, mas signal-cli ausente no PATH ⇒ fail-closed
    r = _stdio([{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                 "params": {"name": "signal_enviar",
                            "arguments": {"destino": "+5511000000000",
                                          "texto": "x"}}}],
               env_extra={"NOMOS_SIGNAL_NUMBER": "+5511999998888",
                          "PATH": ""})
    assert "signal-cli" in r[0]["error"]["message"]


def test_metodo_e_tool_desconhecidos():
    r = _stdio([
        {"jsonrpc": "2.0", "id": 1, "method": "inexistente"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "hackear", "arguments": {}}},
    ])
    assert r[0]["error"]["code"] == -32601
    assert "desconhecida" in r[1]["error"]["message"]


# 2. tools com o signal-cli MOCKADO (nada executa de verdade) ---------------
def test_enviar_e_quem_sou_mockados(monkeypatch):
    mod = _carrega_modulo()
    monkeypatch.setenv("NOMOS_SIGNAL_NUMBER", "+5511999998888")
    chamadas = []

    def cli_falso(args, com_conta=True):
        chamadas.append((tuple(args), com_conta))
        if args and args[0] == "--version":
            return "signal-cli 0.13.0\n"
        return ""                          # send: stdout vazio = ok

    monkeypatch.setattr(mod, "_signalcli", cli_falso)
    quem = mod._rodar_tool("signal_quem_sou", {})
    assert quem["pronto"] is True
    assert quem["signal_cli"].startswith("signal-cli")
    assert quem["conta"].startswith("+55") and "*" in quem["conta"]
    assert quem["conta"] != "+5511999998888"      # mascarado, nunca o cru
    env = mod._rodar_tool("signal_enviar",
                          {"destino": "+5511888887777", "texto": "oi"})
    assert env == {"enviada": True, "destino": "+5511888887777", "grupo": False}
    assert chamadas[-1][0] == ("send", "-m", "oi", "+5511888887777")


def test_enviar_para_grupo(monkeypatch):
    mod = _carrega_modulo()
    monkeypatch.setenv("NOMOS_SIGNAL_NUMBER", "+5511999998888")
    chamadas = []
    monkeypatch.setattr(mod, "_signalcli",
                        lambda args, com_conta=True: chamadas.append(tuple(args)) or "")
    mod._rodar_tool("signal_enviar",
                    {"destino": "GRUPO==", "texto": "oi", "grupo": True})
    assert chamadas[-1] == ("send", "-m", "oi", "-g", "GRUPO==")


def test_limites_e_obrigatorios(monkeypatch):
    import pytest
    mod = _carrega_modulo()
    monkeypatch.setenv("NOMOS_SIGNAL_NUMBER", "+5511999998888")
    monkeypatch.setattr(mod, "_signalcli",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("não deveria chamar")))
    with pytest.raises(ValueError, match="limite"):
        mod._rodar_tool("signal_enviar",
                        {"destino": "+55", "texto": "x" * 9000})
    with pytest.raises(ValueError, match="obrigat"):
        mod._rodar_tool("signal_enviar", {"destino": "", "texto": "x"})


def test_numero_jamais_vaza_em_erros(monkeypatch):
    mod = _carrega_modulo()
    numero = "+5511987654321"
    monkeypatch.setenv("NOMOS_SIGNAL_NUMBER", numero)

    def cli_explode(args, com_conta=True):
        raise RuntimeError(f"falha crua citando {numero} no comando")

    monkeypatch.setattr(mod, "_signalcli", cli_explode)
    resp = mod._despachar({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": "signal_enviar",
                                      "arguments": {"destino": "+5511000000000",
                                                    "texto": "x"}}})
    assert numero not in json.dumps(resp)
    assert "***" in resp["error"]["message"]


# 3. manifesto + trust store + ClienteMCP real ------------------------------
def test_manifesto_valido_e_todas_tools_a3():
    from nomos.interface.mcp_client import carregar_manifesto, nivel_da_tool
    m = carregar_manifesto(MANIFESTO)
    assert m["nome"] == "signal-cli"
    assert m["nivel_padrao"] == "A3"
    for t in ("signal_quem_sou", "signal_enviar"):
        assert nivel_da_tool(m, t) == "A3"
    assert nivel_da_tool(m, "qualquer_outra") == "A3"      # herda o padrão


def test_cliente_mcp_conecta_e_lista():
    from nomos.interface.mcp_client import ClienteMCP, carregar_manifesto
    m = carregar_manifesto(MANIFESTO)
    with ClienteMCP(m, timeout=15, base=MANIFESTO.parent) as cli:
        tools = cli.tools()
    nomes = [t["name"] for t in tools]
    assert nomes == ["signal_quem_sou", "signal_enviar"]
    assert all(t["nivel"] == "A3" for t in tools)


def test_trust_store_confia_e_reconhece(nomos_home):
    from nomos.interface import mcp_catalogo as cat
    from nomos.interface.mcp_client import carregar_manifesto
    nomos_home.mkdir(parents=True, exist_ok=True)
    cat.confiar(nomos_home, carregar_manifesto(MANIFESTO))
    nomes = [s["nome"] for s in cat.listar(nomos_home)["confiaveis"]]
    assert "signal-cli" in nomes
