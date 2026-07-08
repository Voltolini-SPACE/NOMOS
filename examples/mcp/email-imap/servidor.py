#!/usr/bin/env python3
"""Conector NOMOS ↔ E-mail (IMAP) — servidor MCP local (stdio), stdlib pura.

**Entrada por PULL**: LÊ a sua caixa de entrada por IMAP, sem webhook público —
é o NOMOS que puxa, quando você aprova. 100% local-first: fala só com o SEU
servidor IMAP, com a biblioteca padrão do Python (``imaplib``), sem dependências.

Como as leis da casa valem aqui:
- credenciais NUNCA ficam em arquivo: vêm do ambiente
  (``NOMOS_IMAP_HOST`` / ``NOMOS_IMAP_PORT`` / ``NOMOS_IMAP_USER`` /
  ``NOMOS_IMAP_PASSWORD``) e a senha é **redigida** em qualquer eco de erro;
- **SÓ LEITURA, de verdade**: seleciona a caixa em modo ``readonly`` e busca
  cabeçalhos com ``BODY.PEEK`` — nunca marca como lido, nunca apaga, nunca move,
  nunca envia;
- sem credencial, conecta e lista as tools, mas toda chamada falha FECHADO com
  instrução — nunca finge;
- toda tool toca credencial + rede ⇒ nível **A3**: o NOMOS pede a SUA aprovação
  a cada chamada;
- este processo não escreve nada no disco.

Pré-requisitos: um servidor IMAP (Gmail/Outlook/seu provedor) e, quando houver
2FA, uma *app password* dedicada. Detalhes no README.md ao lado.
"""
from __future__ import annotations

import contextlib
import email
import imaplib
import json
import os
import sys
from email.header import decode_header

PROTOCOLO = "2024-11-05"
TIMEOUT_S = 30

TOOLS = [
    {
        "name": "email_imap_quem_sou",
        "description": ("Confere a conexão IMAP e devolve a conta (mascarada), "
                        "o servidor e as contagens total/não-lidas da caixa. "
                        "Comece por aqui."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "email_imap_recentes",
        "description": ("Lê os cabeçalhos das mensagens mais recentes (de, "
                        "assunto, data) — SÓ LEITURA (não marca como lido). "
                        "limite: 1–50; nao_lidas: true traz só as não-lidas."),
        "inputSchema": {"type": "object",
                        "properties": {"limite": {"type": "integer"},
                                       "nao_lidas": {"type": "boolean"}},
                        "required": []},
    },
]


def _conf() -> tuple[str, int, str, str, str]:
    host = os.environ.get("NOMOS_IMAP_HOST", "").strip()
    user = os.environ.get("NOMOS_IMAP_USER", "").strip()
    senha = os.environ.get("NOMOS_IMAP_PASSWORD", "")
    if not (host and user and senha):
        raise PermissionError(
            "sem credencial: defina NOMOS_IMAP_HOST, NOMOS_IMAP_USER e "
            "NOMOS_IMAP_PASSWORD (use uma app password se tiver 2FA) e rode de "
            "novo — este conector nunca guarda a senha em arquivo")
    try:
        port = int(os.environ.get("NOMOS_IMAP_PORT", "993") or 993)
    except ValueError:
        port = 993
    mailbox = os.environ.get("NOMOS_IMAP_MAILBOX", "INBOX") or "INBOX"
    return host, port, user, senha, mailbox


def _mascara(user: str) -> str:
    """Conta reconhecível sem expor o endereço inteiro (ex.: ``jo***@ex***``)."""
    u = user.strip()
    if "@" in u:
        local, _, dom = u.partition("@")
        return f"{local[:2]}***@{dom[:2]}***"
    return f"{u[:2]}***" if len(u) > 2 else "***"


def _redigir(texto: str) -> str:
    """Qualquer eco acidental da senha vira *** — inclusive em erros."""
    senha = os.environ.get("NOMOS_IMAP_PASSWORD", "")
    return texto.replace(senha, "***") if senha else texto


def _decode(valor: str | None) -> str:
    if not valor:
        return ""
    saida = ""
    for txt, enc in decode_header(valor):
        if isinstance(txt, bytes):
            saida += txt.decode(enc or "utf-8", "replace")
        else:
            saida += txt
    return saida


def _conectar():
    """Abre a conexão IMAP SSL e loga. Ponto único; erros curtos e redigidos."""
    host, port, user, senha, mailbox = _conf()
    try:
        M = imaplib.IMAP4_SSL(host, port, timeout=TIMEOUT_S)  # SSL por padrão
        M.login(user, senha)
    except imaplib.IMAP4.error as exc:
        raise RuntimeError(_redigir(
            f"IMAP recusou o login: {exc}")) from None
    except Exception as exc:
        raise RuntimeError(_redigir(
            f"sem resposta do servidor IMAP ({type(exc).__name__}) — confira "
            "host/porta/rede")) from None
    return M, mailbox, user, host


def _rodar_tool(nome: str, args: dict) -> dict:
    if nome == "email_imap_quem_sou":
        M, mailbox, user, host = _conectar()
        try:
            typ, data = M.select(mailbox, readonly=True)   # nunca escreve
            total = int(data[0]) if typ == "OK" and data and data[0] else 0
            typ2, un = M.search(None, "UNSEEN")
            nao = len(un[0].split()) if typ2 == "OK" and un and un[0] else 0
        finally:
            with contextlib.suppress(Exception):
                M.logout()
        return {"conta": _mascara(user), "servidor": host, "caixa": mailbox,
                "total": total, "nao_lidas": nao}
    if nome == "email_imap_recentes":
        limite = min(max(int(args.get("limite") or 10), 1), 50)
        so_nao_lidas = bool(args.get("nao_lidas"))
        M, mailbox, user, host = _conectar()
        try:
            M.select(mailbox, readonly=True)               # readonly: sem \Seen
            typ, data = M.search(None, "UNSEEN" if so_nao_lidas else "ALL")
            ids = data[0].split() if typ == "OK" and data and data[0] else []
            recentes = list(reversed(ids))[:limite]        # mais novas primeiro
            mensagens = []
            for i in recentes:
                # BODY.PEEK NÃO marca como lido (ao contrário de BODY[])
                typ2, d = M.fetch(
                    i, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
                if typ2 != "OK" or not d or not d[0]:
                    continue
                bruto = d[0][1]
                msg = email.message_from_bytes(
                    bruto if isinstance(bruto, bytes) else str(bruto).encode())
                mensagens.append({
                    "de": _decode(msg.get("From", "?"))[:120],
                    "assunto": _decode(msg.get("Subject", "(sem assunto)"))[:200],
                    "data": (msg.get("Date", "") or "")[:40],
                })
        finally:
            with contextlib.suppress(Exception):
                M.logout()
        return {"mensagens": mensagens, "no_criterio": len(ids),
                "so_nao_lidas": so_nao_lidas}
    raise LookupError(f"tool desconhecida: {nome}")


def _despachar(msg: dict) -> dict | None:
    mid = msg.get("id")
    metodo = msg.get("method", "")
    if metodo == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": PROTOCOLO,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "nomos-email-imap", "version": "1.0.0"},
            "instructions": ("Leitura da caixa por IMAP (pull, só-leitura). "
                             "Toda tool usa credencial + rede (A3): o NOMOS pede "
                             "sua aprovação a cada chamada. Sem as variáveis "
                             "NOMOS_IMAP_*, nada funciona — de propósito."),
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
