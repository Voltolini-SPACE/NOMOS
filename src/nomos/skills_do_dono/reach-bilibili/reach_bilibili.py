"""reach-bilibili — metadados de um vídeo do Bilibili, sem binário e sem login.

Por que esta versão existe
--------------------------
O manifesto original exigia o binário `bili` (ausente) e "sessão de
navegador". Para METADADOS públicos de vídeo nada disso é preciso: a API web
aberta do Bilibili (`api.bilibili.com/x/web-interface/view`) responde título,
autor, duração e contadores a partir do BV-id, sem chave. Esta versão fala só
com ela, stdlib pura, credencial NENHUMA — e o manifesto desta versão não
declara A3, porque declarar uso de credencial inexistente mentiria ao gate.

Limite dito na porta: só vídeo público. Removido/privado/região-travada
devolve o código de erro da própria API, traduzido, nunca contornado. E a API
responde em chinês onde responde em chinês — os campos vêm como estão, sem
tradução inventada.

Entrada:  {"bvid": "BV1GJ411x7h7"}
          {"url": "https://www.bilibili.com/video/BV1GJ411x7h7/"}
          opcional: {"salvar_em": "caminho.json"}   (única coisa que usa A1)
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request

NOME_SKILL = "reach-bilibili"
VERSAO = "2.0.0"
UA = f"nomos-{NOME_SKILL}/{VERSAO} (+stdlib urllib; leitura publica; sem login)"
TIMEOUT_S = 15
VARS_PROXY = ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
              "ALL_PROXY", "all_proxy")

_BVID = re.compile(r"(BV[0-9A-Za-z]{10})")

# códigos que a API devolve em `code`; 0 = sucesso. Traduzidos porque o texto
# original vem em chinês e o dono lê português.
_CODIGOS = {
    -400: "requisição malformada",
    -403: "acesso negado (vídeo com restrição)",
    -404: "vídeo não existe ou foi removido",
    62002: "vídeo invisível (privado ou em revisão)",
    62004: "vídeo em revisão",
}


def _ler_argumentos(argv: list[str]) -> tuple[dict, str | None]:
    if len(argv) > 1:
        try:
            with open(argv[1], encoding="utf-8") as fh:
                return json.load(fh), None
        except Exception as exc:
            return {}, f"não li os argumentos de {argv[1]!r}: {exc}"
    if not sys.stdin.isatty():
        bruto = sys.stdin.read().strip()
        if bruto:
            try:
                return json.loads(bruto), None
            except Exception as exc:
                return {}, f"stdin não é JSON: {exc}"
    return {}, None


def _buscar(url: str) -> tuple[bytes, list[str]]:
    import os

    avisos = [f"ignorei proxy do ambiente: {v}" for v in VARS_PROXY
              if os.environ.get(v)]
    abridor = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": "application/json",
                      "Referer": "https://www.bilibili.com/"})
    with abridor.open(req, timeout=TIMEOUT_S) as r:  # noqa: S310 — https fixo
        return r.read(), avisos


def executar(args: dict) -> dict:
    bvid = str(args.get("bvid") or "").strip()
    if not bvid and args.get("url"):
        m = _BVID.search(str(args["url"]))
        bvid = m.group(1) if m else ""
    if not _BVID.fullmatch(bvid or ""):
        return {"ok": False, "skill": NOME_SKILL, "erro_categoria": "entrada",
                "erro": "faltou 'bvid' (BVxxxxxxxxxx) ou 'url' de onde extraí-lo",
                "exemplo": {"url": "https://www.bilibili.com/video/BV1GJ411x7h7"}}

    alvo = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
    try:
        corpo, avisos = _buscar(alvo)
        dados = json.loads(corpo)
    except urllib.error.HTTPError as exc:
        return {"ok": False, "skill": NOME_SKILL, "erro_categoria": "transporte",
                "erro": f"api.bilibili.com respondeu HTTP {exc.code}"}
    except Exception as exc:
        return {"ok": False, "skill": NOME_SKILL, "erro_categoria": "transporte",
                "erro": f"{type(exc).__name__}: {exc}"}

    codigo = dados.get("code", -1)
    if codigo != 0:
        return {"ok": False, "skill": NOME_SKILL,
                "erro_categoria": "nao_acessivel",
                "erro": _CODIGOS.get(codigo,
                                     f"API devolveu code={codigo}"),
                "code_api": codigo}

    d = dados.get("data") or {}
    dono = d.get("owner") or {}
    stat = d.get("stat") or {}
    resultado = {
        "ok": True, "skill": NOME_SKILL, "versao": VERSAO,
        "bvid": bvid,
        "url": f"https://www.bilibili.com/video/{bvid}",
        "titulo": d.get("title"),
        "descricao": (d.get("desc") or "")[:500] or None,
        "autor": dono.get("name"),
        "autor_id": dono.get("mid"),
        "duracao_s": d.get("duration"),
        "publicado_utc": d.get("pubdate"),
        "views": stat.get("view"),
        "likes": stat.get("like"),
        "favoritos": stat.get("favorite"),
        "danmaku": stat.get("danmaku"),
        "partes": len(d.get("pages") or []) or 1,
        "thumbnail": d.get("pic"),
        "fonte": "api web aberta (sem chave, sem login)",
        "avisos": avisos,
    }

    salvar_em = args.get("salvar_em")
    if salvar_em:
        from pathlib import Path
        try:
            destino = Path(str(salvar_em)).expanduser()
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(json.dumps(resultado, ensure_ascii=False,
                                          indent=2), encoding="utf-8")
            resultado["escrita"] = {"ok": True, "caminho": str(destino)}
        except Exception as exc:
            resultado["ok"] = False
            resultado["escrita"] = {"ok": False,
                                    "motivo": f"{type(exc).__name__}: {exc}"}
    return resultado


if __name__ == "__main__":
    args, erro = _ler_argumentos(sys.argv)
    if erro:
        print(json.dumps({"ok": False, "skill": NOME_SKILL,
                          "erro_categoria": "entrada", "erro": erro},
                         ensure_ascii=False))
        raise SystemExit(1)
    saida = executar(args)
    print(json.dumps(saida, ensure_ascii=False))
    raise SystemExit(0 if saida.get("ok") else 1)
