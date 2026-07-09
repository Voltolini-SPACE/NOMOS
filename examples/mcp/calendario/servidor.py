#!/usr/bin/env python3
"""Conector NOMOS ↔ Calendário (.ics LOCAL) — servidor MCP local (stdio), stdlib pura.

**Entrada por leitura de arquivo LOCAL**: LÊ um ``.ics`` que você exportou do seu
app de calendário (Google Agenda, Apple Calendar, Outlook, Proton…). Não fala com
nenhuma rede, nenhuma nuvem, nenhum servidor de terceiros — só abre um arquivo no
SEU disco, com a biblioteca padrão do Python. É a entrada mais local-first
possível para o seu briefing.

Como as leis da casa valem aqui:
- o caminho do arquivo vem SÓ do ambiente (``NOMOS_ICS_PATH``), nunca embutido;
- **ler um arquivo local é A0** (leitura local) — honesto: não é conta conectada
  nem credencial. Mesmo assim, o conector precisa ser **CONFIADO** (``nomos mcp
  confiar calendario``) antes de qualquer chamada; sem confiança, o NOMOS nem
  abre este processo;
- **SÓ LEITURA, de verdade**: abre o arquivo em modo leitura e nunca escreve,
  altera, move ou apaga o ``.ics``;
- sem a variável ``NOMOS_ICS_PATH`` (ou arquivo inexistente), conecta e lista as
  tools, mas toda chamada falha FECHADO com instrução — nunca finge;
- este processo não escreve nada no disco.

Detalhes de uso e de como exportar seu ``.ics`` no README.md ao lado.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timezone

PROTOCOLO = "2024-11-05"
MAX_BYTES = 8 * 1024 * 1024          # trava de sanidade: .ics gigante não trava tudo

TOOLS = [
    {
        "name": "calendario_quem_sou",
        "description": ("Confere o arquivo .ics configurado e devolve o nome do "
                        "arquivo (sem o caminho), quantos eventos há e o intervalo "
                        "de datas. Comece por aqui."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "calendario_hoje",
        "description": ("Lista os eventos de HOJE (data local), em ordem de "
                        "horário — SÓ LEITURA do arquivo local."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "calendario_proximos",
        "description": ("Lista os próximos eventos a partir de agora, em ordem — "
                        "SÓ LEITURA. limite: 1–50 (padrão 10)."),
        "inputSchema": {"type": "object",
                        "properties": {"limite": {"type": "integer"}},
                        "required": []},
    },
]


def _caminho() -> str:
    """O caminho do .ics vem só do ambiente. Sem ele, falha FECHADO."""
    p = os.environ.get("NOMOS_ICS_PATH", "").strip()
    if not p:
        raise PermissionError(
            "sem agenda: defina NOMOS_ICS_PATH apontando para um arquivo .ics "
            "local (exporte do seu app de calendário) e rode de novo — este "
            "conector nunca embute o caminho")
    if not os.path.isfile(p):
        raise RuntimeError(
            "NOMOS_ICS_PATH não aponta para um arquivo existente — confira o "
            "caminho do .ics (este conector só LÊ, nunca cria)")
    return p


def _ler_linhas(caminho: str) -> list[str]:
    """Lê o .ics e desdobra as linhas (RFC 5545: continuação começa com espaço
    ou TAB). Só leitura; trava de tamanho para não engolir um arquivo gigante."""
    if os.path.getsize(caminho) > MAX_BYTES:
        raise RuntimeError("arquivo .ics muito grande (>8 MB) — recuso por sanidade")
    with open(caminho, encoding="utf-8", errors="replace") as fh:
        bruto = fh.read()
    linhas: list[str] = []
    for ln in bruto.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if ln[:1] in (" ", "\t") and linhas:
            linhas[-1] += ln[1:]          # dobra: junta na anterior
        else:
            linhas.append(ln)
    return linhas


def _desescapar(v: str) -> str:
    """Desfaz os escapes de TEXT do iCalendar (\\n, \\, , \\; , \\\\)."""
    out, i = [], 0
    while i < len(v):
        c = v[i]
        if c == "\\" and i + 1 < len(v):
            nxt = v[i + 1]
            out.append({"n": "\n", "N": "\n", ",": ",", ";": ";",
                        "\\": "\\"}.get(nxt, nxt))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _parse_dt(valor: str) -> tuple[datetime, bool] | None:
    """Converte o valor de DTSTART em (datetime local ingênuo, dia_inteiro).

    Aceita ``YYYYMMDD`` (dia inteiro), ``YYYYMMDDTHHMMSS`` (local) e
    ``YYYYMMDDTHHMMSSZ`` (UTC → convertido para o horário local). Formato torto
    ⇒ ``None`` (o evento é ignorado; nunca derruba a leitura)."""
    v = valor.strip()
    try:
        if v.endswith("Z"):
            dt = datetime.strptime(v, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            return dt.astimezone().replace(tzinfo=None), False
        if "T" in v:
            return datetime.strptime(v[:15], "%Y%m%dT%H%M%S"), False
        if len(v) >= 8 and v[:8].isdigit():
            d = datetime.strptime(v[:8], "%Y%m%d")
            return d, True
    except (ValueError, TypeError):
        return None
    return None


def _eventos(caminho: str) -> list[dict]:
    """Extrai os VEVENT do .ics: início (datetime), dia_inteiro, título, local.

    Eventos sem DTSTART parseável são ignorados (fail-safe). Ordena por início."""
    eventos: list[dict] = []
    dentro = False
    atual: dict = {}
    for ln in _ler_linhas(caminho):
        chave_valor = ln.split(":", 1)
        nome = chave_valor[0].split(";", 1)[0].upper()
        valor = chave_valor[1] if len(chave_valor) == 2 else ""
        if ln.upper().startswith("BEGIN:VEVENT"):
            dentro, atual = True, {}
        elif ln.upper().startswith("END:VEVENT"):
            dt = atual.get("_dt")
            if dt is not None:
                eventos.append(atual)
            dentro = False
        elif dentro:
            if nome == "DTSTART":
                par = _parse_dt(valor)
                if par is not None:
                    atual["_dt"], atual["dia_inteiro"] = par[0], par[1]
            elif nome == "SUMMARY":
                atual["titulo"] = _desescapar(valor)[:200]
            elif nome == "LOCATION":
                atual["local"] = _desescapar(valor)[:120]
    eventos.sort(key=lambda e: e["_dt"])
    return eventos


def _quando(ev: dict) -> str:
    dt: datetime = ev["_dt"]
    if ev.get("dia_inteiro"):
        return dt.strftime("%Y-%m-%d") + " (dia inteiro)"
    return dt.strftime("%Y-%m-%d %H:%M")


def _saida(ev: dict) -> dict:
    return {"quando": _quando(ev),
            "titulo": ev.get("titulo", "(sem título)"),
            "local": ev.get("local", "")}


def _rodar_tool(nome: str, args: dict) -> dict:
    caminho = _caminho()
    if nome == "calendario_quem_sou":
        evs = _eventos(caminho)
        primeiro = evs[0]["_dt"].strftime("%Y-%m-%d") if evs else ""
        ultimo = evs[-1]["_dt"].strftime("%Y-%m-%d") if evs else ""
        return {"arquivo": os.path.basename(caminho), "eventos": len(evs),
                "primeiro": primeiro, "ultimo": ultimo}
    if nome == "calendario_hoje":
        hoje = date.today()
        evs = [e for e in _eventos(caminho) if e["_dt"].date() == hoje]
        return {"data": hoje.strftime("%Y-%m-%d"),
                "eventos": [_saida(e) for e in evs], "total": len(evs)}
    if nome == "calendario_proximos":
        limite = min(max(int(args.get("limite") or 10), 1), 50)
        agora = datetime.now()
        evs = [e for e in _eventos(caminho) if e["_dt"] >= agora]
        return {"a_partir_de": agora.strftime("%Y-%m-%d %H:%M"),
                "eventos": [_saida(e) for e in evs[:limite]],
                "total_no_futuro": len(evs)}
    raise LookupError(f"tool desconhecida: {nome}")


def _despachar(msg: dict) -> dict | None:
    mid = msg.get("id")
    metodo = msg.get("method", "")
    if metodo == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": PROTOCOLO,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "nomos-calendario-ics", "version": "1.0.0"},
            "instructions": ("Leitura de um .ics LOCAL (sem rede). Ler arquivo "
                             "local é A0, mas o conector precisa ser confiado. Sem "
                             "a variável NOMOS_ICS_PATH, nada funciona — de "
                             "propósito. Só leitura: nunca altera o arquivo."),
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
                    "error": {"code": -32602, "message": str(exc)}}
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": mid,
                    "error": {"code": -32000, "message": str(exc)}}
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
