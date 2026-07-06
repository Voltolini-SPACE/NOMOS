"""MC32/M1 — MCP client: consumir servers locais com níveis A e gates.

Dogfood hermético: o server consumido nos testes é o PRÓPRIO `nomos mcp
servir` (subprocesso stdio) — protocolo real de ponta a ponta, sem terceiros.
Contratos: manifesto fail-closed, tool desconhecida herda A5, A0 roda direto,
A1+ sem TTY é negada SEM executar, e o NOMOS nunca instala server algum.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from nomos.interface import mcp_client as mc

ROOT = Path(__file__).resolve().parent.parent


def _manifesto(tmp_path: Path, home: Path, **extra) -> Path:
    dados = {"nome": "nomos-espelho",
             "comando": [sys.executable, "-m", "nomos", "mcp", "servir"],
             "nivel_padrao": "A0", **extra}
    p = tmp_path / "manifesto.json"
    p.write_text(json.dumps(dados), encoding="utf-8")
    return p


def _cli(args, home: Path):
    return subprocess.run(
        [sys.executable, "-m", "nomos", *args],
        capture_output=True, text=True, timeout=90, cwd=str(ROOT),
        env={"NOMOS_HOME": str(home), "PATH": ""},
    )


# 1. manifesto fail-closed
def test_manifesto_invalido_e_recusado(tmp_path):
    with pytest.raises(mc.ManifestoInvalido):
        mc.carregar_manifesto(tmp_path / "nao_existe.json")
    ruim = tmp_path / "ruim.json"
    ruim.write_text('{"nome": "x"}', encoding="utf-8")          # sem comando
    with pytest.raises(mc.ManifestoInvalido, match="comando"):
        mc.carregar_manifesto(ruim)
    ruim.write_text('{"nome":"x","comando":["e"],"nivel_padrao":"A9"}',
                    encoding="utf-8")
    with pytest.raises(mc.ManifestoInvalido, match="A9"):
        mc.carregar_manifesto(ruim)


def test_tool_desconhecida_herda_a5_fail_closed():
    manifesto = {"nome": "x", "comando": ["e"], "nivel_padrao": "A5",
                 "tools": {"leitura": "A0"}}
    assert mc.nivel_da_tool(manifesto, "leitura") == "A0"
    assert mc.nivel_da_tool(manifesto, "misteriosa") == "A5"
    assert mc.NIVEL_FAIL_CLOSED == "A5"


# 2. conectar: handshake real + tools anotadas com nível
def test_conectar_lista_tools_do_server_real(tmp_path):
    man = _manifesto(tmp_path, tmp_path, tools={"nomos_status": "A0"})
    proc = _cli(["mcp", "conectar", str(man)], tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "conectado a 'nomos-espelho'" in proc.stdout
    assert "[A0] nomos_status" in proc.stdout
    assert "NÃO assinado" in proc.stdout            # honestidade sobre confiança


# 3. chamar A0: roda direto e devolve conteúdo real
def test_chamar_tool_a0_funciona(tmp_path):
    man = _manifesto(tmp_path, tmp_path)
    proc = _cli(["mcp", "chamar", str(man), "nomos_status"], tmp_path)
    assert proc.returncode == 0, proc.stderr
    corpo = json.loads(proc.stdout)
    assert corpo["so_local"] is True


# 4. nível A1+ sem TTY: negada SEM executar (o gate manda, não o server)
def test_chamar_tool_a1_sem_tty_negada(tmp_path):
    man = _manifesto(tmp_path, tmp_path, tools={"nomos_status": "A1"})
    proc = _cli(["mcp", "chamar", str(man), "nomos_status"], tmp_path)
    assert proc.returncode == 3
    assert "NOMOS-E002" in proc.stderr and "A1" in proc.stderr
    trilha = (tmp_path / "logs" / "audit.jsonl").read_text(encoding="utf-8")
    assert "mcp.client.tool.negada" in trilha
    assert '"mcp.client.tool"' not in trilha        # a chamada NÃO aconteceu


# 5. server que não fala MCP: erro claro, sem traceback
def test_server_quebrado_erro_claro(tmp_path):
    man = tmp_path / "m.json"
    man.write_text(json.dumps({
        "nome": "quebrado", "comando": [sys.executable, "-c", "print('oi')"],
        "nivel_padrao": "A0"}), encoding="utf-8")
    proc = _cli(["mcp", "conectar", str(man)], tmp_path)
    assert proc.returncode == 1
    assert "não conectei" in proc.stderr
    assert "Traceback" not in proc.stderr


# 6. --args inválido: E010 sem chamar nada
def test_args_json_invalido_e010(tmp_path):
    man = _manifesto(tmp_path, tmp_path)
    proc = _cli(["mcp", "chamar", str(man), "nomos_status",
                 "--args", "{isso não é json"], tmp_path)
    assert proc.returncode == 1 and "NOMOS-E010" in proc.stderr
