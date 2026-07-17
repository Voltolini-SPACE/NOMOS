#!/usr/bin/env python3
"""Conector NOMOS ↔ Signal — servidor MCP local (stdio) via signal-cli.

Uma ponte GOVERNADA entre o seu NOMOS e o Signal, usando o **signal-cli LOCAL**
(https://github.com/AsamK/signal-cli), o cliente oficial de linha de comando.
Nada passa por nuvem de terceiros além do próprio Signal — é o mais local-first
dos conectores.

Como as leis da casa valem aqui:
- o número da SUA conta NUNCA fica em arquivo: vem da variável de ambiente
  ``NOMOS_SIGNAL_NUMBER`` (ex.: ``+5511999999999``) e é **redigido** em qualquer
  eco de erro; nas respostas ele só aparece mascarado;
- sem signal-cli instalado ou sem o número, o servidor conecta e lista as tools
  normalmente, mas toda chamada falha FECHADO com instrução — nunca finge;
- toda tool toca credencial + rede ⇒ o manifesto declara nível **A3**: o NOMOS
  pede a SUA aprovação a cada chamada;
- este processo não escreve nada no disco (o estado da conta é do signal-cli);
- o signal-cli é chamado como binário, **sem shell**, com argumentos em lista.

Pré-requisitos (uma vez): instalar o signal-cli e registrar/vincular a conta —
veja o README.md ao lado.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess  # nosec B404 - só o binário signal-cli, sem shell
import sys

# redação de segredo compartilhada entre os conectores (achado P1-5 da
# auditoria de 2026-07-17) — vive em mcp/_comum.py, um nível acima desta
# pasta; ver a docstring de _comum.py para o porquê do sys.path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _comum import redigir as _redigir_comum  # noqa: E402

PROTOCOLO = "2024-11-05"
SIGNAL_CLI = os.environ.get("NOMOS_SIGNAL_CLI", "signal-cli")
TIMEOUT_S = 30
LIMITE_TEXTO = 8000

TOOLS = [
    {
        "name": "signal_quem_sou",
        "description": ("Confirma que o signal-cli está disponível, mostra a "
                        "versão e a sua conta (mascarada). Comece por aqui."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "signal_enviar",
        "description": ("Envia uma mensagem de texto pelo Signal "
                        "(signal-cli send). Exige destino (número +55… ou, com "
                        "grupo=true, o id do grupo) e texto."),
        "inputSchema": {"type": "object",
                        "properties": {"destino": {"type": "string"},
                                       "texto": {"type": "string"},
                                       "grupo": {"type": "boolean"}},
                        "required": ["destino", "texto"]},
    },
]


def _numero() -> str:
    n = os.environ.get("NOMOS_SIGNAL_NUMBER", "").strip()
    if not n:
        raise PermissionError(
            "sem credencial: defina NOMOS_SIGNAL_NUMBER com o número da sua "
            "conta Signal (ex.: +5511999999999) e registre-a no signal-cli — "
            "este conector nunca guarda o número em arquivo")
    return n


def _bin() -> str:
    caminho = shutil.which(SIGNAL_CLI)
    if not caminho:
        raise PermissionError(
            f"signal-cli não encontrado no PATH ({SIGNAL_CLI!r}). Instale-o e "
            "registre sua conta uma vez — veja o README.md ao lado")
    return caminho


def _mascara(numero: str) -> str:
    """Mostra só o suficiente para você reconhecer a conta (nunca o número
    inteiro): 3 primeiros + 2 últimos, resto em ``*``."""
    n = numero.strip()
    if len(n) <= 5:
        return "***"
    return f"{n[:3]}{'*' * (len(n) - 5)}{n[-2:]}"


def _redigir(texto: str) -> str:
    """Qualquer eco acidental do número vira *** — inclusive em erros."""
    return _redigir_comum(texto, os.environ.get("NOMOS_SIGNAL_NUMBER", ""))


def _signalcli(args: list[str], com_conta: bool = True) -> str:
    """Ponto ÚNICO de execução do signal-cli (sem shell). Devolve stdout;
    erros voltam curtos, redigidos, sem stack."""
    base = [_bin()]
    if com_conta:
        base += ["-a", _numero()]
    cmd = [*base, *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,  # nosec B603
                              timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"signal-cli não respondeu em {TIMEOUT_S}s") from None
    if proc.returncode != 0:
        linhas = (proc.stderr or proc.stdout or "erro").strip().splitlines()
        raise RuntimeError(_redigir(
            f"signal-cli falhou: {linhas[-1] if linhas else 'erro'}"))
    return proc.stdout


def _rodar_tool(nome: str, args: dict) -> dict:
    if nome == "signal_quem_sou":
        num = _numero()                       # fail-closed se faltar
        versao = (_signalcli(["--version"], com_conta=False).strip()
                  or "signal-cli")
        return {"conta": _mascara(num), "signal_cli": versao, "pronto": True}
    if nome == "signal_enviar":
        destino = str(args.get("destino", "")).strip()
        texto = str(args.get("texto", ""))
        if not destino or not texto.strip():
            raise ValueError("destino e texto são obrigatórios")
        if len(texto) > LIMITE_TEXTO:
            raise ValueError(f"texto passa do limite de {LIMITE_TEXTO} "
                             f"caracteres ({len(texto)})")
        alvo = ["-g", destino] if args.get("grupo") else [destino]
        _signalcli(["send", "-m", texto, *alvo])
        return {"enviada": True, "destino": destino,
                "grupo": bool(args.get("grupo"))}
    raise LookupError(f"tool desconhecida: {nome}")


def _despachar(msg: dict) -> dict | None:
    mid = msg.get("id")
    metodo = msg.get("method", "")
    if metodo == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": PROTOCOLO,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "nomos-signal", "version": "1.0.0"},
            "instructions": ("Ponte com o Signal via signal-cli local. Toda "
                             "tool usa credencial + rede (A3): o NOMOS pede sua "
                             "aprovação a cada chamada. Sem NOMOS_SIGNAL_NUMBER "
                             "ou sem signal-cli, nada funciona — de propósito."),
        }}
    if isinstance(metodo, str) and metodo.startswith("notifications/"):
        return None
    if metodo == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if metodo == "tools/call":
        params = msg.get("params") or {}
        nome = str(params.get("name", ""))
        args = params.get("arguments") or {}
        try:
            resultado = _rodar_tool(nome, args if isinstance(args, dict) else {})
        except (LookupError, ValueError, PermissionError) as exc:
            return {"jsonrpc": "2.0", "id": mid,
                    "error": {"code": -32602, "message": _redigir(str(exc))}}
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": mid,
                    "error": {"code": -32000, "message": _redigir(str(exc))}}
        corpo = json.dumps(resultado, ensure_ascii=False, indent=2)
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "content": [{"type": "text", "text": corpo}], "isError": False}}
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601,
                      "message": f"método não suportado: {metodo}"}}


def principal() -> int:
    """Loop MCP sobre stdio; encerra no EOF (o NOMOS gerencia o processo)."""
    for linha in sys.stdin:
        linha = linha.strip()
        if not linha:
            continue
        try:
            msg = json.loads(linha)
        except Exception:
            continue
        resposta = _despachar(msg)
        if resposta is not None:
            sys.stdout.write(json.dumps(resposta, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
