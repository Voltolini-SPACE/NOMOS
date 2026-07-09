"""NOMOS interface.mcp_client — consumir servers MCP locais (MC32/M1).

O NOMOS passa a USAR servers Model Context Protocol como capacidades externas,
sem trair a governança:

- o server roda como **subprocesso local** (stdio) de um comando declarado num
  **manifesto JSON** que o usuário escreveu/aceitou — o NOMOS **nunca instala**
  server algum, só executa o que o manifesto manda;
- cada tool recebe um **nível A0–A6 no manifesto**; tool não listada herda o
  ``nivel_padrao`` — e o padrão do padrão é **A5_CODE_EXEC** (fail-closed:
  capacidade desconhecida é tratada como execução de código);
- a chamada passa pelo **gate de sempre**: A0 segue direto; qualquer outro
  nível exige aprovação humana interativa (sem TTY ⇒ nega);
- sessão **one-shot**: sobe, handshake, executa, encerra — sem daemon.

Manifesto (exemplo):
    {"nome": "nomos-espelho",
     "comando": ["python3", "-m", "nomos", "mcp", "servir"],
     "nivel_padrao": "A0",
     "tools": {"write_file": "A1", "run_command": "A5"}}
"""
from __future__ import annotations

import contextlib
import json
import subprocess
from pathlib import Path

from nomos.kernel.policy import Category

PROTOCOLO = "2024-11-05"
NIVEIS = {
    "A0": Category.READ_LOCAL,
    "A1": Category.WRITE_LOCAL,
    "A2": Category.NET_EGRESS,
    # A3 de conector = usar UMA CONTA CONECTADA sua (rótulo mais fiel que
    # "usar credencial"; mesmo efeito REQUIRE_APPROVAL — nada afrouxa). Os usos
    # diretos de credencial (cofre, âncora HMAC) seguem chamando CRED_USE à mão.
    "A3": Category.CONNECTOR_USE,
    "A4": Category.DEVICE_SCREEN,
    "A5": Category.CODE_EXEC,
    "A6": Category.DESTRUCTIVE,
}
NIVEL_FAIL_CLOSED = "A5"          # tool desconhecida = execução de código


class ManifestoInvalido(Exception):
    pass


class McpErro(Exception):
    pass


def carregar_manifesto(caminho: Path) -> dict:
    """Lê e valida o manifesto. Fail-closed: qualquer campo torto ⇒ erro."""
    try:
        dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ManifestoInvalido(f"manifesto não encontrado: {caminho}") from None
    except Exception:
        raise ManifestoInvalido(f"manifesto não é JSON válido: {caminho}") from None
    nome = dados.get("nome")
    comando = dados.get("comando")
    if not nome or not isinstance(nome, str):
        raise ManifestoInvalido("manifesto sem campo 'nome'")
    if (not isinstance(comando, list) or not comando
            or not all(isinstance(c, str) for c in comando)):
        raise ManifestoInvalido("'comando' deve ser lista de strings não vazia")
    nivel_padrao = str(dados.get("nivel_padrao", NIVEL_FAIL_CLOSED))
    if nivel_padrao not in NIVEIS:
        raise ManifestoInvalido(f"nivel_padrao desconhecido: {nivel_padrao}")
    tools = dados.get("tools", {})
    if not isinstance(tools, dict):
        raise ManifestoInvalido("'tools' deve ser um objeto tool->nível")
    for t, n in tools.items():
        if str(n) not in NIVEIS:
            raise ManifestoInvalido(f"nível desconhecido para {t!r}: {n}")
    return {"nome": nome, "comando": comando, "nivel_padrao": nivel_padrao,
            "tools": {str(t): str(n) for t, n in tools.items()}}


def nivel_da_tool(manifesto: dict, tool: str) -> str:
    return manifesto["tools"].get(tool, manifesto["nivel_padrao"])


class ClienteMCP:
    """Sessão one-shot com um server MCP local via stdio."""

    def __init__(self, manifesto: dict, timeout: float = 30.0, base=None):
        self.manifesto = manifesto
        self.timeout = timeout
        # ``base`` = diretório do manifesto. O ``comando`` é PORTÁTIL (ex.:
        # ["python3", "servidor.py"]) para o hash de confiança ser estável em
        # qualquer máquina; a resolução do caminho relativo acontece AQUI, em
        # runtime, rodando o subprocesso com cwd=base. Sem base (comando
        # autocontido) roda no cwd atual, como antes.
        self._base = str(base) if base else None
        self._proc: subprocess.Popen | None = None
        self._mid = 0

    def __enter__(self) -> "ClienteMCP":
        import queue as _queue
        import threading as _threading
        self._proc = subprocess.Popen(
            self.manifesto["comando"], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            encoding="utf-8", cwd=self._base)
        # leitor em thread: readline direto bloquearia PARA SEMPRE se o
        # comando do manifesto não falar MCP — o timeout precisa valer
        self._fila: _queue.Queue = _queue.Queue()
        proc = self._proc

        def _ler() -> None:
            # leitor daemon: erro de I/O só encerra o stream — o None
            # abaixo sinaliza o fim para quem consome a fila
            with contextlib.suppress(Exception):
                for linha in proc.stdout:
                    self._fila.put(linha)
            self._fila.put(None)          # EOF/erro: sinaliza fim

        _threading.Thread(target=_ler, daemon=True).start()
        init = self._rpc("initialize", {
            "protocolVersion": PROTOCOLO,
            "capabilities": {}, "clientInfo": {"name": "nomos-mcp-client"}})
        self.server_info = init.get("serverInfo", {})
        self._notificar("notifications/initialized")
        return self

    def __exit__(self, *exc) -> None:
        if self._proc is not None:
            try:
                self._proc.stdin.close()
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()

    def _enviar(self, payload: dict) -> None:
        assert self._proc and self._proc.stdin
        self._proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()

    def _notificar(self, metodo: str) -> None:
        self._enviar({"jsonrpc": "2.0", "method": metodo})

    def _rpc(self, metodo: str, params: dict | None = None) -> dict:
        import queue as _queue
        import time as _time
        self._mid += 1
        self._enviar({"jsonrpc": "2.0", "id": self._mid, "method": metodo,
                      **({"params": params} if params is not None else {})})
        prazo = _time.monotonic() + self.timeout
        while True:
            restante = prazo - _time.monotonic()
            if restante <= 0:
                raise McpErro(f"server MCP não respondeu em {self.timeout:.0f}s "
                              "(o comando do manifesto fala MCP?)")
            try:
                linha = self._fila.get(timeout=restante)
            except _queue.Empty:
                raise McpErro(f"server MCP não respondeu em {self.timeout:.0f}s "
                              "(o comando do manifesto fala MCP?)") from None
            if linha is None:
                raise McpErro("server MCP encerrou sem responder (handshake?)")
            try:
                msg = json.loads(linha)
            except Exception:
                raise McpErro("server MCP respondeu algo que não é JSON") from None
            if not isinstance(msg, dict) or msg.get("id") != self._mid:
                continue                  # notificação/log: não é a resposta
            if "error" in msg:
                raise McpErro(str(msg["error"].get("message", "erro do server")))
            return msg.get("result", {})

    def tools(self) -> list[dict]:
        """tools/list anotada com o nível A de cada tool (do manifesto)."""
        resultado = self._rpc("tools/list")
        anotadas = []
        for t in resultado.get("tools", []):
            anotadas.append({**t, "nivel": nivel_da_tool(self.manifesto,
                                                         t.get("name", ""))})
        return anotadas

    def chamar(self, tool: str, argumentos: dict | None = None) -> dict:
        return self._rpc("tools/call",
                         {"name": tool, "arguments": argumentos or {}})
