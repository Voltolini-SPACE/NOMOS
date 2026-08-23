"""reach-youtube-meta — metadados de um vídeo do YouTube, sem chave e sem binário.

Por que esta versão existe
--------------------------
O manifesto original declarava `yt-dlp` como binário obrigatório. Para
METADADOS (título, autor, thumbnail) ele é um canhão contra mosquito: o
YouTube publica um endpoint oEmbed aberto, sem chave, que responde isso em uma
requisição. Esta versão fala SÓ com ele, em stdlib pura — nada a instalar,
nada a autenticar.

O que ela NÃO faz, dito na porta: não baixa vídeo, não lê transcrição, não vê
duração nem contagem de views (o oEmbed não os publica). Quem precisar disso
precisa do yt-dlp de volta — e aí é outra skill, com outro custo declarado.

Promessas de transporte (mesmas do reach-rss):
* fala DIRETO com a origem — proxies do ambiente são ignorados e reportados;
* TLS sempre verificado; sem redirecionamento silencioso;
* uma linha de JSON no stdout; exit 0 só quando o trabalho saiu inteiro.

Entrada:  {"url": "https://www.youtube.com/watch?v=..."}  ou  {"id": "dQw4..."}
          opcional: {"salvar_em": "caminho.json"}   (única coisa que usa A1)
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

NOME_SKILL = "reach-youtube-meta"
VERSAO = "2.0.0"
UA = f"nomos-{NOME_SKILL}/{VERSAO} (+stdlib urllib; sem login)"
TIMEOUT_S = 15
VARS_PROXY = ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
              "ALL_PROXY", "all_proxy")

# formas de URL que carregam o id do vídeo; a ordem importa (a mais comum vem
# primeiro). `shorts/` e `youtu.be/` são as que mais aparecem em link colado.
_FORMAS_DE_ID = (
    re.compile(r"[?&]v=([A-Za-z0-9_-]{6,20})"),
    re.compile(r"youtu\.be/([A-Za-z0-9_-]{6,20})"),
    re.compile(r"/shorts/([A-Za-z0-9_-]{6,20})"),
    re.compile(r"/embed/([A-Za-z0-9_-]{6,20})"),
)


def _extrair_id(url: str) -> str | None:
    for forma in _FORMAS_DE_ID:
        m = forma.search(url)
        if m:
            return m.group(1)
    return None


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
    """GET direto na origem. Devolve (corpo, avisos)."""
    import os

    avisos = [f"ignorei proxy do ambiente: {v}" for v in VARS_PROXY
              if os.environ.get(v)]
    abridor = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/json"})
    with abridor.open(req, timeout=TIMEOUT_S) as r:  # noqa: S310 — https fixo
        return r.read(), avisos


def executar(args: dict) -> dict:
    video_id = str(args.get("id") or "").strip()
    url_dada = str(args.get("url") or "").strip()
    if url_dada and not video_id:
        video_id = _extrair_id(url_dada) or ""
    if not video_id:
        return {"ok": False, "skill": NOME_SKILL, "erro_categoria": "entrada",
                "erro": "faltou 'url' (ou 'id') de um vídeo do YouTube",
                "exemplo": {"url": "https://www.youtube.com/watch?v=jNQXAC9IVRw"}}

    alvo = ("https://www.youtube.com/oembed?format=json&url="
            + urllib.parse.quote(f"https://www.youtube.com/watch?v={video_id}",
                                 safe=""))
    try:
        corpo, avisos = _buscar(alvo)
        dados = json.loads(corpo)
    except urllib.error.HTTPError as exc:
        cat = "nao_encontrado" if exc.code in (400, 404) else "transporte"
        return {"ok": False, "skill": NOME_SKILL, "erro_categoria": cat,
                "erro": f"YouTube respondeu HTTP {exc.code} para o id {video_id!r}"
                        + (" — vídeo inexistente ou privado" if cat == "nao_encontrado" else "")}
    except Exception as exc:
        return {"ok": False, "skill": NOME_SKILL, "erro_categoria": "transporte",
                "erro": f"{type(exc).__name__}: {exc}"}

    resultado = {
        "ok": True, "skill": NOME_SKILL, "versao": VERSAO,
        "video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "titulo": dados.get("title"),
        "canal": dados.get("author_name"),
        "canal_url": dados.get("author_url"),
        "thumbnail": dados.get("thumbnail_url"),
        "tipo": dados.get("type"),
        "fonte": "oembed (aberto, sem chave)",
        "limites": "sem duração/views/transcrição — o oEmbed não os publica",
        "avisos": avisos,
    }

    salvar_em = args.get("salvar_em")
    if salvar_em:
        from pathlib import Path
        try:
            destino = Path(str(salvar_em)).expanduser()
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(json.dumps(resultado, ensure_ascii=False, indent=2),
                               encoding="utf-8")
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
