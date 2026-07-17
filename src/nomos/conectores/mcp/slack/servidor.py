#!/usr/bin/env python3
"""Conector NOMOS ↔ Slack — servidor MCP local (stdio), stdlib pura.

Usa o **Incoming Webhook oficial** do Slack
(https://api.slack.com/messaging/webhooks): você cria o webhook no seu
workspace, e o NOMOS faz um POST de texto para ele. Sem bibliotecas
não-oficiais, sem token de usuário, sem browser automation.

Como as leis da casa valem aqui:
- a credencial é a **URL do webhook** — que é secreta (quem a tem, posta no
  seu canal). Vem SÓ do ambiente (``NOMOS_SLACK_WEBHOOK``), nunca de arquivo, e
  é **redigida** em qualquer eco de erro;
- **recuso apontar o envio para fora de ``hooks.slack.com``** — a URL tem de ser
  um webhook do Slack, senão falha FECHADO (evita virar um POST genérico);
- toda tool = credencial + rede ⇒ nível **A3**: o NOMOS pede a SUA aprovação a
  cada chamada; em script/CI a resposta é sempre "não";
- **só ENVIO**: receber exigiria um app/socket permanente (fora do desenho
  local-first) — está dito, não escondido;
- sem a variável, conecta e lista as tools, mas toda chamada falha FECHADO com
  instrução — nunca finge que enviou;
- este processo não escreve nada no disco.

Como criar o webhook: Slack → Apps → "Incoming WebHooks" → Add to Slack →
escolha o canal → copie a URL. Detalhes no README.md ao lado.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request

# redação de segredo compartilhada entre os conectores (achado P1-5 da
# auditoria de 2026-07-17) — vive em mcp/_comum.py, um nível acima desta
# pasta; ver a docstring de _comum.py para o porquê do sys.path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _comum import redigir as _redigir_comum  # noqa: E402

PROTOCOLO = "2024-11-05"
TIMEOUT_S = 20
LIMITE_TEXTO = 4000                      # Slack recomenda blocos <= ~4000 chars
PREFIXO = "https://hooks.slack.com/"


def _webhook() -> str:
    url = os.environ.get("NOMOS_SLACK_WEBHOOK", "").strip()
    if not url:
        raise PermissionError(
            "sem credencial: defina NOMOS_SLACK_WEBHOOK com a URL do Incoming "
            "Webhook do seu workspace (Slack → Apps → Incoming WebHooks). Sem "
            "ela nada é enviado — de propósito")
    if not url.startswith(PREFIXO):
        raise ValueError(
            "NOMOS_SLACK_WEBHOOK tem de ser uma URL https://hooks.slack.com/… "
            "— recuso apontar o envio para outro destino")
    return url


def _redigir(texto: str) -> str:
    """A URL do webhook é secreta: qualquer eco dela em erro vira ***."""
    return _redigir_comum(texto, os.environ.get("NOMOS_SLACK_WEBHOOK", ""))


def _mascara(url: str) -> str:
    """Webhook reconhecível sem expor os segmentos secretos."""
    m = re.match(r"https://hooks\.slack\.com/services/([^/]+)/", url)
    time_id = m.group(1) if m else ""
    return f"hooks.slack.com/services/{time_id[:3]}***/***"


def enviar(texto: str) -> dict:
    url = _webhook()
    dados = json.dumps({"text": texto}).encode("utf-8")
    req = urllib.request.Request(
        url, data=dados, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:  # nosec B310
            corpo = r.read().decode("utf-8", "replace").strip()
    except urllib.error.HTTPError as exc:
        try:
            detalhe = exc.read().decode("utf-8", "replace").strip()[:120]
        except Exception:
            detalhe = ""
        raise RuntimeError(_redigir(
            f"Slack respondeu {exc.code}: {detalhe or 'erro'}")) from None
    except Exception as exc:
        raise RuntimeError(_redigir(
            f"sem resposta do Slack ({type(exc).__name__})")) from None
    if corpo != "ok":                    # webhook OK devolve o texto "ok"
        raise RuntimeError(f"Slack não confirmou o envio: {corpo[:120] or '?'}")
    return {"enviada": True}


def _rodar_tool(nome: str, args: dict) -> dict:
    if nome == "slack_quem_sou":
        url = _webhook()                 # valida presença + formato (sem rede)
        return {"webhook": _mascara(url),
                "observacao": ("um webhook não pode ser validado sem enviar; "
                               "isto só confirma que está configurado")}
    if nome == "slack_enviar":
        texto = str(args.get("texto", ""))
        if not texto.strip():
            raise ValueError("texto é obrigatório")
        if len(texto) > LIMITE_TEXTO:
            raise ValueError(f"texto passa de {LIMITE_TEXTO} caracteres")
        return enviar(texto)
    raise LookupError(f"tool desconhecida: {nome}")


def _despachar(msg: dict) -> dict | None:
    mid = msg.get("id")
    metodo = msg.get("method", "")
    if metodo == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": PROTOCOLO,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "nomos-slack-webhook", "version": "1.0.0"},
            "instructions": ("Envio pelo Incoming Webhook OFICIAL do Slack, só "
                             "envio. Sem NOMOS_SLACK_WEBHOOK nada funciona, de "
                             "propósito. Toda tool é A3 (aprovação sua)."),
        }}
    if isinstance(metodo, str) and metodo.startswith("notifications/"):
        return None
    if metodo == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": [
            {"name": "slack_quem_sou",
             "description": ("Confirma que o webhook está configurado e devolve "
                             "a URL mascarada — sem enviar nada. Comece aqui."),
             "inputSchema": {"type": "object", "properties": {}}},
            {"name": "slack_enviar",
             "description": ("Envia uma mensagem de texto para o canal do "
                             "webhook. texto: obrigatório (até 4000 chars)."),
             "inputSchema": {"type": "object",
                             "properties": {"texto": {"type": "string"}},
                             "required": ["texto"]}},
        ]}}
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
