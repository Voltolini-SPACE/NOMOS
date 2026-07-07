#!/usr/bin/env python3
"""Conector NOMOS ↔ E-mail — servidor MCP local (stdio), stdlib pura.

Envia e-mail pelo SEU servidor SMTP (o do seu provedor, ou um local) usando
apenas ``smtplib`` da biblioteca padrão — zero dependências, zero serviço
de terceiros embutido. É o "terceiro canal" do briefing, ao lado de
Telegram e WhatsApp.

Credenciais SÓ por ambiente (nunca em arquivo):
  export NOMOS_SMTP_HOST="smtp.seuprovedor.com"
  export NOMOS_SMTP_PORT="587"            # 587 = STARTTLS (padrão)
  export NOMOS_SMTP_USER="voce@dominio.com"
  export NOMOS_SMTP_PASSWORD="sua-senha-ou-app-password"
  export NOMOS_SMTP_FROM="voce@dominio.com"   # opcional; padrão = USER

Sem host+user+senha, toda chamada falha FECHADO com instrução — nunca
finge que enviou. A senha JAMAIS aparece em erros (redação ativa). Toda
tool usa credencial + rede ⇒ nível A3 (sua aprovação a cada chamada).

Segurança de transporte: porta 587 usa STARTTLS (padrão); 465 usa SSL
direto; qualquer outra porta é tratada como texto claro APENAS se você
declarar ``NOMOS_SMTP_INSECURE=1`` (opt-in explícito, p/ servidor local
de teste) — senão o envio é recusado.
"""
from __future__ import annotations

import json
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from email.utils import parseaddr

PROTOCOLO = "2024-11-05"
TIMEOUT_S = 20
LIMITE_TEXTO = 100_000          # e-mail comporta bem mais que um SMS

TOOLS = [
    {
        "name": "email_quem_sou",
        "description": ("Valida a configuração SMTP (conecta e autentica, "
                        "sem enviar nada) e mostra o remetente. Comece por "
                        "aqui."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "email_enviar",
        "description": ("Envia um e-mail de texto pelo seu servidor SMTP. "
                        "Exige destinatario, assunto e texto."),
        "inputSchema": {"type": "object",
                        "properties": {"destinatario": {"type": "string"},
                                       "assunto": {"type": "string"},
                                       "texto": {"type": "string"}},
                        "required": ["destinatario", "assunto", "texto"]},
    },
]


def _cfg() -> dict:
    host = os.environ.get("NOMOS_SMTP_HOST", "").strip()
    user = os.environ.get("NOMOS_SMTP_USER", "").strip()
    senha = os.environ.get("NOMOS_SMTP_PASSWORD", "")
    if not host or not user or not senha:
        raise PermissionError(
            "sem credenciais SMTP: defina NOMOS_SMTP_HOST, NOMOS_SMTP_USER e "
            "NOMOS_SMTP_PASSWORD (e opcional NOMOS_SMTP_PORT/FROM). Sem elas "
            "nada é enviado — de propósito")
    try:
        porta = int(os.environ.get("NOMOS_SMTP_PORT", "587"))
    except ValueError:
        raise ValueError("NOMOS_SMTP_PORT precisa ser um número") from None
    return {"host": host, "porta": porta, "user": user, "senha": senha,
            "from": os.environ.get("NOMOS_SMTP_FROM", "").strip() or user,
            "inseguro": os.environ.get("NOMOS_SMTP_INSECURE", "") == "1"}


def _redigir(texto: str) -> str:
    senha = os.environ.get("NOMOS_SMTP_PASSWORD", "")
    return texto.replace(senha, "***") if senha else texto


def _conectar(cfg: dict):
    """Abre a sessão SMTP com a segurança certa para a porta. Fail-closed
    contra texto claro, salvo opt-in explícito (servidor local de teste)."""
    if cfg["porta"] == 465:
        smtp = smtplib.SMTP_SSL(cfg["host"], cfg["porta"], timeout=TIMEOUT_S,
                                context=ssl.create_default_context())
    else:
        smtp = smtplib.SMTP(cfg["host"], cfg["porta"], timeout=TIMEOUT_S)
        smtp.ehlo()
        if smtp.has_extn("starttls"):
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
        elif not cfg["inseguro"]:
            smtp.close()
            raise RuntimeError(
                "o servidor não oferece STARTTLS e NOMOS_SMTP_INSECURE não "
                "está ligado — recuso enviar senha/e-mail em texto claro")
    smtp.login(cfg["user"], cfg["senha"])
    return smtp


def _rodar_tool(nome: str, args: dict) -> dict:
    if nome == "email_quem_sou":
        cfg = _cfg()
        smtp = _conectar(cfg)
        try:
            smtp.noop()
        finally:
            smtp.quit()
        return {"remetente": cfg["from"], "host": cfg["host"],
                "porta": cfg["porta"], "autenticado": True}
    if nome == "email_enviar":
        cfg = _cfg()
        destinatario = str(args.get("destinatario", "")).strip()
        assunto = str(args.get("assunto", "")).strip()
        texto = str(args.get("texto", ""))
        if "@" not in parseaddr(destinatario)[1]:
            raise ValueError("destinatario não é um e-mail válido")
        if not assunto:
            raise ValueError("assunto é obrigatório")
        if not texto.strip():
            raise ValueError("texto é obrigatório")
        if len(texto) > LIMITE_TEXTO:
            raise ValueError(f"texto passa de {LIMITE_TEXTO} caracteres")
        msg = EmailMessage()
        msg["From"] = cfg["from"]
        msg["To"] = destinatario
        msg["Subject"] = assunto
        msg.set_content(texto)
        smtp = _conectar(cfg)
        try:
            smtp.send_message(msg)
        finally:
            smtp.quit()
        return {"enviado": True, "para": destinatario, "assunto": assunto}
    raise LookupError(f"tool desconhecida: {nome}")


def _despachar(msg: dict) -> dict | None:
    mid = msg.get("id")
    metodo = msg.get("method", "")
    if metodo == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": PROTOCOLO,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "nomos-email-smtp", "version": "1.0.0"},
            "instructions": ("Envio de e-mail pelo SEU servidor SMTP "
                             "(stdlib). Sem NOMOS_SMTP_HOST/USER/PASSWORD "
                             "nada funciona, de propósito. Toda tool é A3 "
                             "(credencial + rede)."),
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
