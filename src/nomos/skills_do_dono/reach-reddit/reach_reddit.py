"""reach-reddit — posts públicos de um subreddit, sem binário e sem login.

Por que esta versão existe
--------------------------
O manifesto original exigia o binário `rdt` (ausente nesta máquina) e uma
"sessão de navegador". Para conteúdo PÚBLICO nada disso é necessário: o Reddit
serve qualquer listagem pública como JSON — basta acrescentar `.json` ao
caminho. Esta versão fala só com `www.reddit.com`, em stdlib pura, sem
credencial nenhuma — e por isso o manifesto desta versão NÃO declara A3:
declarar uso de credencial que não existe seria mentir para o gate.

Limite dito na porta: só o que é público. E MEDIDO em 23/08: o Reddit passou
a responder 403 ao `.json` anônimo mesmo para subreddit público e mesmo com
User-Agent de navegador — mas mantém o feed `.rss` aberto. Então o caminho é:
JSON primeiro (mais rico: pontos e nº de comentários); se vier 403, cai para o
RSS em modo DEGRADADO, declarado na saída (`modo: "degradado_rss"`), onde
pontos e comentários não existem e os campos vêm como None — nunca inventados.
Subreddit privado/quarentena falha nos DOIS caminhos e aí sim é
`nao_acessivel`.

Promessas de transporte: direto na origem (proxies ignorados e reportados),
TLS sempre verificado, uma linha de JSON no stdout, exit 0 só com trabalho
inteiro.

Entrada:  {"subreddit": "selfhosted"}                — hot por padrão
          {"subreddit": "python", "ordem": "top", "limite": 5}
          {"url": "https://www.reddit.com/r/rust/"}  — aceita link colado
          opcional: {"salvar_em": "caminho.json"}    (única coisa que usa A1)
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request

NOME_SKILL = "reach-reddit"
VERSAO = "2.0.0"
UA = f"nomos-{NOME_SKILL}/{VERSAO} (+stdlib urllib; leitura publica; sem login)"
TIMEOUT_S = 15
ORDENS = ("hot", "new", "top", "rising")
LIMITE_MAX = 50
VARS_PROXY = ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
              "ALL_PROXY", "all_proxy")

_SUB_VALIDO = re.compile(r"^[A-Za-z0-9_]{2,21}$")
_SUB_NA_URL = re.compile(r"reddit\.com/r/([A-Za-z0-9_]{2,21})")


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
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/json"})
    with abridor.open(req, timeout=TIMEOUT_S) as r:  # noqa: S310 — https fixo
        return r.read(), avisos


def _post(filho: dict) -> dict:
    d = filho.get("data") or {}
    return {
        "titulo": d.get("title"),
        "autor": d.get("author"),
        "pontos": d.get("score"),
        "comentarios": d.get("num_comments"),
        "criado_utc": d.get("created_utc"),
        "permalink": ("https://www.reddit.com" + d["permalink"])
                     if d.get("permalink") else None,
        "url_externa": d.get("url_overridden_by_dest") or d.get("url"),
        "flair": d.get("link_flair_text"),
        "fixado": bool(d.get("stickied")),
        "nsfw": bool(d.get("over_18")),
    }


def _do_rss(corpo: bytes) -> list[dict]:
    """Entradas do feed Atom no MESMO formato de `_post` — campos que o RSS
    não publica vêm como None, nunca inventados."""
    import xml.etree.ElementTree as ET

    ns = {"a": "http://www.w3.org/2005/Atom"}
    raiz = ET.fromstring(corpo)
    saida = []
    for e in raiz.findall("a:entry", ns):
        link = e.find("a:link", ns)
        autor = e.find("a:author/a:name", ns)
        saida.append({
            "titulo": e.findtext("a:title", default=None, namespaces=ns),
            # removeprefix, nunca lstrip("/u/"): lstrip come CARACTERES e um
            # autor chamado "uva" viraria "va" — mesma classe do bug do
            # subreddit "rust", pega pelo mesmo B005.
            "autor": (autor.text or "").removeprefix("/u/")
                     if autor is not None else None,
            "pontos": None, "comentarios": None,
            "criado_utc": e.findtext("a:updated", default=None, namespaces=ns),
            "permalink": link.get("href") if link is not None else None,
            "url_externa": None, "flair": None, "fixado": None, "nsfw": None,
        })
    return saida


def executar(args: dict) -> dict:
    # `.removeprefix`, não `.lstrip("r/")`: lstrip remove CARACTERES do
    # conjunto, então "rust" viraria "ust" — o ruff (B005) pegou antes do bug.
    sub = str(args.get("subreddit") or "").strip().strip("/")
    sub = sub.removeprefix("r/")
    if not sub and args.get("url"):
        m = _SUB_NA_URL.search(str(args["url"]))
        sub = m.group(1) if m else ""
    if not sub or not _SUB_VALIDO.match(sub):
        return {"ok": False, "skill": NOME_SKILL, "erro_categoria": "entrada",
                "erro": "faltou 'subreddit' (ou 'url' de onde extraí-lo)",
                "exemplo": {"subreddit": "selfhosted", "ordem": "hot",
                            "limite": 10}}

    ordem = str(args.get("ordem") or "hot").lower()
    if ordem not in ORDENS:
        return {"ok": False, "skill": NOME_SKILL, "erro_categoria": "entrada",
                "erro": f"ordem {ordem!r} não existe; use uma de {ORDENS}"}
    try:
        limite = max(1, min(int(args.get("limite") or 10), LIMITE_MAX))
    except (TypeError, ValueError):
        return {"ok": False, "skill": NOME_SKILL, "erro_categoria": "entrada",
                "erro": "'limite' precisa ser um número"}

    posts, fonte, modo, avisos = [], "", "json", []
    alvo = (f"https://www.reddit.com/r/{sub}/{ordem}.json"
            f"?limit={limite}&raw_json=1")
    try:
        corpo, avisos = _buscar(alvo)
        dados = json.loads(corpo)
        filhos = ((dados.get("data") or {}).get("children")) or []
        posts = [_post(f) for f in filhos if f.get("kind") == "t3"]
        fonte = "listagem pública .json (sem login, sem chave)"
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            return {"ok": False, "skill": NOME_SKILL,
                    "erro_categoria": "limite_de_taxa",
                    "erro": "Reddit pediu calma (HTTP 429); tente de novo em "
                            "alguns segundos"}
        if exc.code not in (403, 404):
            return {"ok": False, "skill": NOME_SKILL,
                    "erro_categoria": "transporte",
                    "erro": f"HTTP {exc.code} em r/{sub}"}
        # 403/404 no JSON: pode ser o bloqueio anônimo do Reddit, não o
        # subreddit. O RSS decide qual dos dois é.
        try:
            corpo, avisos2 = _buscar(
                f"https://www.reddit.com/r/{sub}/{ordem}.rss?limit={limite}")
            posts = _do_rss(corpo)[:limite]
            avisos = avisos2 + [
                "Reddit negou o .json anônimo (bloqueio de rede/UA); usei o "
                "feed .rss — sem pontos nem nº de comentários"]
            fonte, modo = "feed público .rss (fallback)", "degradado_rss"
        except Exception:
            return {"ok": False, "skill": NOME_SKILL,
                    "erro_categoria": "nao_acessivel",
                    "erro": (f"r/{sub} negado no .json (HTTP {exc.code}) E no "
                             ".rss — subreddit inexistente, privado ou em "
                             "quarentena; esta skill só lê o que é público")}
    except Exception as exc:
        return {"ok": False, "skill": NOME_SKILL, "erro_categoria": "transporte",
                "erro": f"{type(exc).__name__}: {exc}"}

    resultado = {
        "ok": True, "skill": NOME_SKILL, "versao": VERSAO,
        "subreddit": sub, "ordem": ordem,
        "fonte": fonte, "modo": modo,
        "itens_devolvidos": len(posts),
        "posts": posts,
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
