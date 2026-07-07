"""MC31/C1 — MCP server local: protocolo real via pipes, somente leitura.

Fala JSON-RPC/MCP de verdade com `nomos mcp servir` num subprocesso
(initialize → tools/list → tools/call) e prova os contratos: read-only,
redação de segredos na memória, erros fail-closed e auditoria.
"""
import json
import subprocess
import sys
from pathlib import Path

from nomos.interface import mcp_server
from _cli_env import cli_env

ROOT = Path(__file__).resolve().parent.parent


def _sessao_mcp(home: Path, mensagens: list[dict]) -> list[dict]:
    """Envia mensagens ao servidor real via stdio e devolve as respostas."""
    entrada = "".join(json.dumps(m) + "\n" for m in mensagens)
    proc = subprocess.run(
        [sys.executable, "-m", "nomos", "mcp", "servir"],
        input=entrada, capture_output=True, text=True, timeout=60,
        cwd=str(ROOT), env=cli_env(home),
    )
    return [json.loads(linha) for linha in proc.stdout.splitlines() if linha.strip()]


def test_handshake_e_tools_list(tmp_path):
    respostas = _sessao_mcp(tmp_path, [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ])
    assert len(respostas) == 2                      # notificação não responde
    init = respostas[0]["result"]
    assert init["protocolVersion"] == mcp_server.PROTOCOLO
    assert init["serverInfo"]["name"] == "nomos"
    assert "somente leitura" in init["instructions"]
    nomes = {t["name"] for t in respostas[1]["result"]["tools"]}
    assert nomes == {"nomos_status", "nomos_capacidades", "nomos_evidencias",
                     "nomos_memoria_buscar", "nomos_roteador_explicar"}


def test_tool_status_responde_dados_reais(tmp_path):
    respostas = _sessao_mcp(tmp_path, [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "nomos_status", "arguments": {}}},
    ])
    corpo = json.loads(respostas[0]["result"]["content"][0]["text"])
    assert corpo["so_local"] is True                 # cadeado default
    assert "motores_prontos" in corpo


def test_memoria_buscar_rediz_segredos(tmp_path):
    from nomos.cognition.memory import Memory
    chave = "sk-" + "Q" * 30
    Memory(tmp_path / "memory.db").remember("note", f"minha chave é {chave}")
    respostas = _sessao_mcp(tmp_path, [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "nomos_memoria_buscar",
                    "arguments": {"consulta": "chave"}}},
    ])
    texto = respostas[0]["result"]["content"][0]["text"]
    assert chave not in texto, "segredo vazou pelo MCP"


def test_erros_fail_closed(tmp_path):
    respostas = _sessao_mcp(tmp_path, [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "tool_inexistente", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 2, "method": "resources/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "nomos_roteador_explicar",
                    "arguments": {"modalidade": "inexistente"}}},
    ])
    assert respostas[0]["error"]["code"] == -32602
    assert respostas[1]["error"]["code"] == -32601
    assert "desconhecida" in respostas[2]["error"]["message"]


def test_servidor_e_read_only_e_audita(tmp_path):
    # 1ª execução: bootstrap normal do NOMOS_HOME (policy, consent, dirs…)
    _sessao_mcp(tmp_path, [{"jsonrpc": "2.0", "id": 0, "method": "tools/list"}])
    antes = {str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")}
    # 2ª execução: a tool call em si não pode criar NADA além da auditoria
    _sessao_mcp(tmp_path, [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "nomos_capacidades", "arguments": {}}},
    ])
    depois = {str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")}
    novas = {n for n in depois - antes if "audit" not in n}
    assert not novas, f"MCP escreveu além da auditoria: {novas}"
    trilha = tmp_path / "logs" / "audit.jsonl"
    assert trilha.exists() and "mcp.tool" in trilha.read_text(encoding="utf-8")


def test_json_invalido_nao_derruba_o_loop(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "nomos", "mcp", "servir"],
        input='isto não é json\n{"jsonrpc":"2.0","id":9,"method":"tools/list"}\n',
        capture_output=True, text=True, timeout=60, cwd=str(ROOT),
        env=cli_env(tmp_path),
    )
    linhas = [json.loads(x) for x in proc.stdout.splitlines() if x.strip()]
    assert linhas[0]["error"]["code"] == -32700      # parse error
    assert "tools" in linhas[1]["result"]            # e o loop seguiu vivo


def test_cli_mcp_tools_lista(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "nomos", "mcp", "tools"],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT),
        env=cli_env(tmp_path),
    )
    assert proc.returncode == 0
    assert "SOMENTE LEITURA" in proc.stdout
    assert "nomos_status" in proc.stdout
