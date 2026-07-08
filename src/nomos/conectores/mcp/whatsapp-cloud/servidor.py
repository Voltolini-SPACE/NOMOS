#!/usr/bin/env python3
"""Conector NOMOS ↔ WhatsApp — servidor MCP local (stdio), stdlib pura.

Usa EXCLUSIVAMENTE a **WhatsApp Business Cloud API oficial da Meta**
(https://developers.facebook.com/docs/whatsapp/cloud-api). Não usamos —
e não vamos usar — bibliotecas não-oficiais que se passam pelo aplicativo:
elas violam os termos do WhatsApp e derrubam número de gente.

O que a Meta exige de VOCÊ antes deste conector funcionar (sem atalho):
  1. conta Meta Business + app criado no developers.facebook.com;
  2. um número de WhatsApp Business (o de teste da Meta serve p/ começar);
  3. o PHONE_NUMBER_ID do número e um ACCESS_TOKEN do app.

Credenciais SÓ por ambiente (nunca em arquivo):
  export NOMOS_WHATSAPP_TOKEN="EAAG..."
  export NOMOS_WHATSAPP_PHONE_ID="123456789012345"

Sem as duas variáveis, toda chamada falha FECHADO com esta instrução —
nunca fingimos que enviou. Toda tool = credencial + rede ⇒ nível A3
(aprovação SUA a cada chamada). Recebimento de mensagens exige webhook
público (fora do desenho local-first) — por isso este conector é de
ENVIO; está dito, não escondido.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

PROTOCOLO = "2024-11-05"
API_BASE = os.environ.get("NOMOS_WHATSAPP_API",
                          "https://graph.facebook.com/v21.0")
TIMEOUT_S = 20
LIMITE_TEXTO = 4096

TOOLS = [
    {
        "name": "whatsapp_enviar_texto",
        "description": ("Envia mensagem de texto pela Cloud API oficial. "
                        "Exige numero destino em formato internacional "
                        "(ex.: 5511999998888) e texto. Fora da janela de "
                        "24h do contato, a Meta exige template aprovado — "
                        "aí use whatsapp_enviar_template."),
        "inputSchema": {"type": "object",
                        "properties": {"numero": {"type": "string"},
                                       "texto": {"type": "string"}},
                        "required": ["numero", "texto"]},
    },
    {
        "name": "whatsapp_enviar_template",
        "description": ("Envia um template APROVADO na sua conta (ex.: "
                        "hello_world). Necessário para iniciar conversa "
                        "fora da janela de 24h."),
        "inputSchema": {"type": "object",
                        "properties": {"numero": {"type": "string"},
                                       "template": {"type": "string"},
                                       "idioma": {"type": "string"}},
                        "required": ["numero", "template"]},
    },
]


def _credenciais() -> tuple[str, str]:
    token = os.environ.get("NOMOS_WHATSAPP_TOKEN", "").strip()
    phone_id = os.environ.get("NOMOS_WHATSAPP_PHONE_ID", "").strip()
    if not token or not phone_id:
        raise PermissionError(
            "sem credenciais: defina NOMOS_WHATSAPP_TOKEN e "
            "NOMOS_WHATSAPP_PHONE_ID (Cloud API oficial da Meta — veja o "
            "README deste conector). Sem elas nada é enviado — de propósito")
    return token, phone_id


def _redigir(texto: str) -> str:
    tok = os.environ.get("NOMOS_WHATSAPP_TOKEN", "").strip()
    return texto.replace(tok, "***") if tok else texto


def chamar_api(payload: dict) -> dict:
    token, phone_id = _credenciais()
    url = f"{API_BASE}/{phone_id}/messages"
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:  # nosec B310
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            detalhe = json.loads(exc.read().decode()).get(
                "error", {}).get("message", "")
        except Exception:
            detalhe = ""
        raise RuntimeError(_redigir(
            f"Meta respondeu {exc.code}: {detalhe or 'erro'}")) from None
    except Exception as exc:
        raise RuntimeError(_redigir(
            f"sem resposta da Cloud API ({type(exc).__name__})")) from None


def _rodar_tool(nome: str, args: dict) -> dict:
    if nome == "whatsapp_enviar_texto":
        numero = str(args.get("numero", "")).strip().lstrip("+")
        texto = str(args.get("texto", ""))
        if not numero.isdigit() or not (8 <= len(numero) <= 15):
            raise ValueError("numero deve ser internacional, só dígitos "
                             "(ex.: 5511999998888)")
        if not texto.strip():
            raise ValueError("texto é obrigatório")
        if len(texto) > LIMITE_TEXTO:
            raise ValueError(f"texto passa de {LIMITE_TEXTO} caracteres")
        r = chamar_api({"messaging_product": "whatsapp", "to": numero,
                        "type": "text", "text": {"body": texto}})
        ids = [m.get("id") for m in r.get("messages", [])]
        return {"enviada": True, "message_id": ids[0] if ids else None}
    if nome == "whatsapp_enviar_template":
        numero = str(args.get("numero", "")).strip().lstrip("+")
        template = str(args.get("template", "")).strip()
        idioma = str(args.get("idioma") or "pt_BR")
        if not numero.isdigit() or not template:
            raise ValueError("numero (só dígitos) e template são "
                             "obrigatórios")
        r = chamar_api({"messaging_product": "whatsapp", "to": numero,
                        "type": "template",
                        "template": {"name": template,
                                     "language": {"code": idioma}}})
        ids = [m.get("id") for m in r.get("messages", [])]
        return {"enviada": True, "message_id": ids[0] if ids else None,
                "template": template}
    raise LookupError(f"tool desconhecida: {nome}")


def _despachar(msg: dict) -> dict | None:
    mid = msg.get("id")
    metodo = msg.get("method", "")
    if metodo == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": PROTOCOLO,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "nomos-whatsapp-cloud",
                           "version": "1.0.0"},
            "instructions": ("Cloud API OFICIAL da Meta, só envio (receber "
                             "exige webhook público — fora do local-first). "
                             "Sem NOMOS_WHATSAPP_TOKEN/PHONE_ID nada "
                             "funciona, de propósito. Toda tool é A3."),
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
