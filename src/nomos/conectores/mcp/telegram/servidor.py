#!/usr/bin/env python3
"""Conector NOMOS ↔ Telegram — servidor MCP local (stdio), stdlib pura.

O que ele é: uma ponte GOVERNADA entre o seu NOMOS e a Bot API OFICIAL do
Telegram (https://core.telegram.org/bots/api). Nada de bibliotecas de
terceiros, nada de protocolo não-oficial, nada de conta pessoal scrapeada.

Como as leis da casa valem aqui:
- o token do bot NUNCA fica em arquivo: vem da variável de ambiente
  ``NOMOS_TELEGRAM_TOKEN`` no momento de rodar (e jamais aparece em erros
  ou logs — qualquer eco do token é redigido);
- sem token, o servidor conecta e lista tools normalmente, mas toda
  chamada falha FECHADO com instrução do que fazer — nunca finge;
- toda tool deste conector toca rede + credencial ⇒ o manifesto declara
  nível **A3** (CONNECTOR_USE): o NOMOS pede a SUA aprovação a cada chamada;
- este processo não lê nem escreve nada no disco.

Uso (resumo; detalhes no README.md ao lado):
  1. crie um bot com o @BotFather e copie o token;
  2. ``export NOMOS_TELEGRAM_TOKEN="123456:ABC..."``;
  3. ``nomos mcp confiar examples/mcp/telegram/manifesto.json``
  4. ``nomos mcp chamar examples/mcp/telegram/manifesto.json \
        telegram_quem_sou '{}'``
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

PROTOCOLO = "2024-11-05"
API_BASE = os.environ.get("NOMOS_TELEGRAM_API",
                          "https://api.telegram.org")
LIMITE_TEXTO = 4096          # limite oficial do sendMessage
TIMEOUT_S = 15

TOOLS = [
    {
        "name": "telegram_quem_sou",
        "description": ("Valida o token e devolve a identidade do bot "
                        "(getMe). Comece por aqui."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "telegram_enviar",
        "description": ("Envia uma mensagem de texto pelo bot "
                        "(sendMessage). Exige chat_id (número do chat ou "
                        "@canal) e texto (até 4096 caracteres)."),
        "inputSchema": {"type": "object",
                        "properties": {"chat_id": {"type": "string"},
                                       "texto": {"type": "string"}},
                        "required": ["chat_id", "texto"]},
    },
    {
        "name": "telegram_atualizacoes",
        "description": ("Lê mensagens recebidas pelo bot (getUpdates). "
                        "Devolve remetente, chat, texto e o next_offset "
                        "para a próxima leitura (passe offset para não "
                        "repetir)."),
        "inputSchema": {"type": "object",
                        "properties": {"offset": {"type": "integer"},
                                       "limite": {"type": "integer"}},
                        "required": []},
    },
]


def _token() -> str:
    tok = os.environ.get("NOMOS_TELEGRAM_TOKEN", "").strip()
    if not tok:
        raise PermissionError(
            "sem credencial: defina NOMOS_TELEGRAM_TOKEN com o token do seu "
            "bot (crie um com o @BotFather) e rode de novo — este conector "
            "nunca guarda o token em arquivo")
    return tok


def _redigir(texto: str) -> str:
    """Qualquer eco acidental do token vira *** — inclusive em erros."""
    tok = os.environ.get("NOMOS_TELEGRAM_TOKEN", "").strip()
    return texto.replace(tok, "***") if tok else texto


def chamar_api(metodo: str, params: dict) -> dict:
    """POST na Bot API oficial. Erros voltam curtos, redigidos, sem stack."""
    url = f"{API_BASE}/bot{_token()}/{metodo}"
    corpo = json.dumps(params).encode()
    req = urllib.request.Request(
        url, data=corpo, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:  # nosec B310
            dados = json.loads(r.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            detalhe = json.loads(exc.read().decode()).get("description", "")
        except Exception:
            detalhe = ""
        raise RuntimeError(_redigir(
            f"Telegram respondeu {exc.code}: {detalhe or 'erro'}")) from None
    except Exception as exc:
        raise RuntimeError(_redigir(
            f"sem resposta do Telegram ({type(exc).__name__}) — confira "
            "sua rede e o token")) from None
    if not dados.get("ok"):
        raise RuntimeError(_redigir(
            f"Telegram recusou: {dados.get('description', 'sem detalhe')}"))
    return dados["result"]


def _rodar_tool(nome: str, args: dict) -> dict:
    if nome == "telegram_quem_sou":
        r = chamar_api("getMe", {})
        return {"id": r.get("id"), "nome": r.get("first_name"),
                "usuario": f"@{r.get('username', '?')}",
                "pode_entrar_em_grupos": r.get("can_join_groups")}
    if nome == "telegram_enviar":
        chat_id = str(args.get("chat_id", "")).strip()
        texto = str(args.get("texto", ""))
        if not chat_id or not texto.strip():
            raise ValueError("chat_id e texto são obrigatórios")
        if len(texto) > LIMITE_TEXTO:
            raise ValueError(f"texto passa do limite oficial de "
                             f"{LIMITE_TEXTO} caracteres ({len(texto)})")
        r = chamar_api("sendMessage", {"chat_id": chat_id, "text": texto})
        return {"enviada": True, "message_id": r.get("message_id"),
                "chat_id": r.get("chat", {}).get("id")}
    if nome == "telegram_atualizacoes":
        limite = min(max(int(args.get("limite") or 10), 1), 20)
        params: dict = {"limit": limite, "timeout": 0,
                        "allowed_updates": ["message"]}
        if args.get("offset") is not None:
            params["offset"] = int(args["offset"])
        rs = chamar_api("getUpdates", params)
        mensagens, maior = [], None
        for up in rs:
            maior = up.get("update_id", maior)
            m = up.get("message") or {}
            if not m:
                continue
            mensagens.append({
                "de": (m.get("from") or {}).get("first_name", "?"),
                "chat_id": (m.get("chat") or {}).get("id"),
                "texto": (m.get("text") or "(sem texto)")[:500],
                "ts": m.get("date"),
            })
        return {"mensagens": mensagens,
                "next_offset": (maior + 1) if maior is not None else None}
    raise LookupError(f"tool desconhecida: {nome}")


def _despachar(msg: dict) -> dict | None:
    mid = msg.get("id")
    metodo = msg.get("method", "")
    if metodo == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": PROTOCOLO,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "nomos-telegram", "version": "1.0.0"},
            "instructions": ("Ponte oficial Bot API do Telegram. Toda tool "
                             "usa rede + credencial (A3): o NOMOS pede sua "
                             "aprovação a cada chamada. Sem "
                             "NOMOS_TELEGRAM_TOKEN, nada funciona — de "
                             "propósito."),
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
            resultado = _rodar_tool(nome, args if isinstance(args, dict)
                                    else {})
        except (LookupError, ValueError, PermissionError) as exc:
            return {"jsonrpc": "2.0", "id": mid,
                    "error": {"code": -32602, "message": _redigir(str(exc))}}
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": mid,
                    "error": {"code": -32000, "message": _redigir(str(exc))}}
        corpo = json.dumps(resultado, ensure_ascii=False, indent=2)
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "content": [{"type": "text", "text": corpo}],
            "isError": False}}
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
