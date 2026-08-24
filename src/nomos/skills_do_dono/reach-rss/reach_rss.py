"""Skill NOMOS: reach-rss — le um feed RSS/Atom falando DIRETO com a origem.

Permissoes declaradas no skill.json: A1_WRITE_LOCAL + A2_NET_EGRESS.
O que NAO esta declarado limita o codigo, e nao o contrario:
  * sem A0_READ_LOCAL  -> o unico arquivo lido e o JSON de argumentos que o
    proprio runner entrega em sys.argv[1]. Por isso `file://`, `ftp://` e
    afins sao RECUSADOS: urllib abriria um arquivo local de bom grado, e isso
    seria leitura local sem gate;
  * sem A5_CODE_EXEC   -> nada de subprocess. Existe `curl` no PATH da caixa,
    mas chamar binario e execucao de codigo. A rede sai por urllib, stdlib.

O ambiente foi medido, nao suposto: PATH=/usr/local/bin:/usr/bin:/bin, onde
`python3` e o framework 3.12 (o de /usr/bin e shim do xcrun e falha), e
`feedparser` NAO esta instalado nele. Ou seja: nesta maquina o caminho normal
e o modo degradado. Ele nao e um plano B envergonhado — e testado e anunciado.
"""
from __future__ import annotations

import gzip
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import datetime, timezone
from html.parser import HTMLParser

NOME_SKILL = "reach-rss"

LIMITE_ITENS_PADRAO = 20
LIMITE_ITENS_TETO = 200
RESUMO_MAX_PADRAO = 280
TIMEOUT_PADRAO = 20.0
TIMEOUT_TETO = 120.0
MAX_BYTES_PADRAO = 8 * 1024 * 1024

# User-Agent honesto: identifica quem esta batendo na porta. Feed publico nao
# exige isso, mas varios servidores respondem 403 a cliente sem UA, e mentir
# sobre ser um navegador seria comecar a conversa com uma mentira.
USER_AGENT = f"nomos-{NOME_SKILL}/1.0 (+leitor de feeds; contato via o dono da instalacao)"

# Variaveis de ambiente que fariam urllib desviar a requisicao para um proxy.
# A skill promete falar DIRETO com a origem, entao elas sao ignoradas de forma
# explicita (ProxyHandler({})) e o nome das que existiam vai no relatorio —
# ignorar em silencio seria a mesma opacidade que a promessa combate.
VARS_PROXY = ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
              "ALL_PROXY", "all_proxy")


# --------------------------------------------------------------------------
# entrada
# --------------------------------------------------------------------------

def _ler_argumentos(argv: list[str]) -> tuple[dict, str | None]:
    """Devolve (argumentos, erro). Arquivo em argv[1]; senao stdin; senao {}.

    Sem argumento NAO se inventa uma URL padrao: bater num feed que ninguem
    pediu e egress de rede nao solicitado, exatamente o que o gate A2 existe
    para evitar. O default sensato aqui e recusar e dizer o que falta.
    """
    if len(argv) > 1:
        try:
            with open(argv[1], encoding="utf-8") as fh:
                dados = json.load(fh)
        except Exception as exc:
            return {}, f"argumentos ilegiveis em {argv[1]!r}: {type(exc).__name__}: {exc}"
        if not isinstance(dados, dict):
            return {}, "o JSON de argumentos precisa ser um objeto"
        return dados, None
    # isatty() evita travar esperando um stdin que nunca vem quando alguem
    # roda a skill na mao, sem redirecionar nada.
    if not sys.stdin.isatty():
        bruto = sys.stdin.read().strip()
        if bruto:
            try:
                dados = json.loads(bruto)
            except Exception as exc:
                return {}, f"stdin nao e JSON valido: {type(exc).__name__}: {exc}"
            if not isinstance(dados, dict):
                return {}, "o JSON de stdin precisa ser um objeto"
            return dados, None
    return {}, None


def _inteiro(valor, padrao: int, minimo: int, maximo: int) -> int:
    try:
        n = int(valor)
    except (TypeError, ValueError):
        return padrao
    return max(minimo, min(maximo, n))


def _numero(valor, padrao: float, minimo: float, maximo: float) -> float:
    try:
        n = float(valor)
    except (TypeError, ValueError):
        return padrao
    return max(minimo, min(maximo, n))


# --------------------------------------------------------------------------
# rede
# --------------------------------------------------------------------------

class _RedirecionaSoHttp(urllib.request.HTTPRedirectHandler):
    """Corta redirecionamento que sai de http(s).

    O handler padrao aceita tambem `ftp:`, e um 302 para `file:` ou `ftp:`
    transformaria uma permissao de rede em leitura de disco ou noutro
    protocolo. O feed manda no conteudo, nunca no alcance da skill.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        esquema = urllib.parse.urlsplit(newurl).scheme.lower()
        if esquema not in ("http", "https"):
            raise urllib.error.HTTPError(
                newurl, code,
                f"redirecionamento para esquema '{esquema}' bloqueado", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _abridor() -> urllib.request.OpenerDirector:
    # ProxyHandler({}) VAZIO nao e o mesmo que omitir o handler: omitir faz o
    # urllib ler as variaveis de ambiente e ir por um proxy. O dicionario vazio
    # e a forma de dizer "nenhum proxy, para nenhum esquema".
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _RedirecionaSoHttp(),
        urllib.request.HTTPSHandler(),
    )


def _descomprime(dados: bytes, codificacao: str) -> tuple[bytes, str | None]:
    """Content-Encoding aplicado pelo servidor mesmo tendo pedido `identity`."""
    cod = (codificacao or "").strip().lower()
    if cod in ("", "identity"):
        return dados, None
    try:
        if cod == "gzip":
            return gzip.decompress(dados), None
        if cod == "deflate":
            try:
                return zlib.decompress(dados), None
            except zlib.error:
                return zlib.decompress(dados, -zlib.MAX_WBITS), None
    except Exception as exc:
        return dados, f"nao consegui descomprimir Content-Encoding '{cod}': {type(exc).__name__}"
    return dados, f"Content-Encoding '{cod}' desconhecido: entreguei os bytes crus ao parser"


def buscar(url: str, timeout: float, max_bytes: int) -> tuple[dict | None, dict]:
    """Faz UMA requisicao direta. Devolve (resposta, erro) — um dos dois e None."""
    partes = urllib.parse.urlsplit(url)
    if partes.scheme.lower() not in ("http", "https"):
        return None, {
            "categoria": "entrada",
            "mensagem": (f"esquema '{partes.scheme or '(vazio)'}' recusado: esta skill so "
                         "fala http/https. Sem A0_READ_LOCAL no manifesto, ler "
                         "file:// seria acessar disco sem permissao declarada"),
        }
    if not partes.netloc:
        return None, {"categoria": "entrada", "mensagem": f"URL sem host: {url!r}"}

    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        # Accept honesto: e um leitor de feed, nao um navegador disfarcado.
        "Accept": "application/atom+xml, application/rss+xml, application/xml;q=0.9, text/xml;q=0.9, */*;q=0.5",
        "Accept-Encoding": "identity",
    })
    try:
        with _abridor().open(req, timeout=timeout) as resp:
            # read(max+1) para DETECTAR o estouro; ler so `max` deixaria um XML
            # cortado passando por feed valido, que e o tipo de silencio que
            # esta skill nao pode produzir.
            bruto = resp.read(max_bytes + 1)
            # Cabecalhos lidos AQUI, do HTTPMessage, que compara nome SEM
            # diferenciar maiuscula. Converter para dict antes tornaria a busca
            # sensivel a caixa, e servidor real manda "Content-type" com t
            # minusculo (o http.server da propria stdlib manda assim). O efeito
            # seria mudo e grave: Content-encoding: gzip nao detectado e bytes
            # comprimidos entregues ao parser como se fossem XML.
            content_type = resp.headers.get("Content-Type", "") or ""
            content_encoding = resp.headers.get("Content-Encoding", "") or ""
            status = getattr(resp, "status", None) or resp.getcode()
            url_final = resp.geturl()
    except urllib.error.HTTPError as exc:
        return None, {"categoria": "http", "status": exc.code,
                      "mensagem": f"o servidor respondeu HTTP {exc.code} {exc.reason}"}
    except urllib.error.URLError as exc:
        return None, {"categoria": "rede",
                      "mensagem": f"nao cheguei na origem: {exc.reason}"}
    except Exception as exc:
        return None, {"categoria": "rede",
                      "mensagem": f"falha ao buscar: {type(exc).__name__}: {exc}"}

    if len(bruto) > max_bytes:
        return None, {"categoria": "tamanho",
                      "mensagem": (f"feed maior que o limite de {max_bytes} bytes. "
                                   "Nao entrego XML cortado como se fosse o feed "
                                   "inteiro; aumente 'max_bytes' se quiser mesmo")}

    corpo, aviso = _descomprime(bruto, content_encoding)
    return {"bytes": corpo, "status": status, "url_final": url_final,
            "content_type": content_type,
            "bytes_recebidos": len(bruto),
            "aviso": aviso}, {}


# --------------------------------------------------------------------------
# texto
# --------------------------------------------------------------------------

class _TiraTags(HTMLParser):
    """Descasca HTML de resumo. Resumo de feed vem cheio de markup e o consumidor
    desta skill quer texto; deixar `<p>` e `&amp;` passar empurra o problema
    para quem le."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pedacos: list[str] = []
        self._mudo = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._mudo += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._mudo:
            self._mudo -= 1

    def handle_data(self, data):
        if not self._mudo:
            self.pedacos.append(data)


def limpar(texto: str | None, limite: int | None = None) -> str:
    if not texto:
        return ""
    p = _TiraTags()
    try:
        p.feed(texto)
        p.close()
        saida = "".join(p.pedacos)
    except Exception:
        # HTML podre nao pode derrubar a leitura do feed inteiro: cai para
        # remocao bruta de tags e segue.
        saida = re.sub(r"<[^>]*>", " ", texto)
    saida = html.unescape(saida)
    saida = re.sub(r"\s+", " ", saida).strip()
    if limite and len(saida) > limite:
        # reticencia explicita: quem le sabe que foi cortado
        saida = saida[:limite].rstrip() + "…"
    return saida


def _data_iso(bruta: str | None) -> str | None:
    """RFC 822 (RSS) ou RFC 3339 (Atom) -> ISO 8601. None quando nao da.

    Devolver None e informacao: mostra que a origem mandou data em formato que
    nao reconhecemos. Chutar 'agora' seria fabricar dado."""
    if not bruta:
        return None
    bruta = bruta.strip()
    try:
        from email.utils import parsedate_to_datetime
        d = parsedate_to_datetime(bruta)
        if d is not None:
            return d.isoformat()
    except Exception:  # noqa: S110 — data RFC-2822 ilegível: tenta ISO abaixo
        pass           # antes de desistir; feed ruim não derruba o leitor.
    try:
        return datetime.fromisoformat(bruta.replace("Z", "+00:00")).isoformat()
    except Exception:
        return None


# --------------------------------------------------------------------------
# parser degradado (stdlib)
# --------------------------------------------------------------------------

def _tag(elemento) -> str:
    """Nome sem namespace. Feeds usam prefixos diferentes para a mesma coisa;
    comparar o tag cru faria o parser errar em Atom com namespace default."""
    t = elemento.tag
    if not isinstance(t, str):
        return ""
    return t.rsplit("}", 1)[-1].lower()


def _filho(elemento, *nomes):
    alvo = {n.lower() for n in nomes}
    for f in elemento:
        if _tag(f) in alvo:
            return f
    return None


def _filho_ou(elemento, nome, reserva):
    """`_filho(x, n) or reserva` NAO serve: Element sem filhos e falsy, entao um
    <channel> vazio seria descartado. Pior, o proprio teste de verdade e
    DeprecationWarning e vira excecao em Python futuro."""
    achado = _filho(elemento, nome)
    return reserva if achado is None else achado


def _texto_de(elemento, *nomes) -> str:
    f = _filho(elemento, *nomes)
    if f is None:
        return ""
    return "".join(f.itertext()).strip()


def _link_de(elemento) -> str:
    """RSS poe o link no texto; Atom poe em @href, possivelmente em varios
    <link> com rel diferente. `alternate` e o que um humano abriria."""
    reserva = ""
    for f in elemento:
        if _tag(f) != "link":
            continue
        href = (f.attrib.get("href") or "").strip()
        if href:
            rel = (f.attrib.get("rel") or "alternate").strip().lower()
            if rel == "alternate":
                return href
            reserva = reserva or href
        else:
            texto = "".join(f.itertext()).strip()
            if texto:
                return texto
    return reserva


def parsear_degradado(dados: bytes) -> tuple[dict, list[str]]:
    """RSS 2.0, RSS 1.0/RDF e Atom com xml.etree. Sem dependencia externa."""
    import xml.etree.ElementTree as ET

    problemas: list[str] = []
    # xml.etree e vulneravel a expansao exponencial de entidade ("billion
    # laughs"): um feed hostil de poucos KB vira gigabytes de RAM. A stdlib nao
    # tem chave para desligar isso, entao a defesa e recusar declaracao de
    # ENTITY — que feed legitimo praticamente nunca traz.
    cabeca = dados[:4096].lower()
    if b"<!entity" in cabeca or b"<!entity" in dados[:65536].lower():
        raise ValueError("o documento declara <!ENTITY>: recusado por risco de "
                         "expansao de entidade (billion laughs) no parser da stdlib")
    raiz = ET.fromstring(dados)

    nome_raiz = _tag(raiz)
    if nome_raiz == "rss":
        formato = "rss"
        canal = _filho_ou(raiz, "channel", raiz)
        itens = [e for e in canal.iter() if _tag(e) == "item"]
    elif nome_raiz == "feed":
        formato = "atom"
        canal = raiz
        itens = [e for e in raiz if _tag(e) == "entry"]
    elif nome_raiz == "rdf":
        formato = "rss1.0-rdf"
        canal = _filho_ou(raiz, "channel", raiz)
        itens = [e for e in raiz.iter() if _tag(e) == "item"]
    else:
        formato = f"desconhecido(<{nome_raiz}>)"
        canal = raiz
        itens = [e for e in raiz.iter() if _tag(e) in ("item", "entry")]
        problemas.append(f"raiz <{nome_raiz}> nao e rss/feed/RDF: extrai o que deu, "
                         "trate o resultado com desconfianca")

    cabecalho = {
        "titulo": limpar(_texto_de(canal, "title")),
        "link": _link_de(canal),
        "descricao": limpar(_texto_de(canal, "description", "subtitle"), 300),
        "formato": formato,
    }
    return {"feed": cabecalho, "itens_crus": itens}, problemas


def item_degradado(elemento, resumo_max: int) -> dict:
    data_bruta = (_texto_de(elemento, "pubdate") or _texto_de(elemento, "published")
                  or _texto_de(elemento, "updated") or _texto_de(elemento, "date"))
    resumo = (_texto_de(elemento, "description") or _texto_de(elemento, "summary")
              or _texto_de(elemento, "encoded") or _texto_de(elemento, "content"))
    return {
        "titulo": limpar(_texto_de(elemento, "title")) or None,
        "link": _link_de(elemento) or None,
        "data": data_bruta or None,
        "data_iso": _data_iso(data_bruta),
        "resumo": limpar(resumo, resumo_max) or None,
        "id": (_texto_de(elemento, "guid") or _texto_de(elemento, "id") or None),
        "autor": limpar(_texto_de(elemento, "author") or _texto_de(elemento, "creator"), 120) or None,
    }


# --------------------------------------------------------------------------
# parser feedparser
# --------------------------------------------------------------------------

def carregar_feedparser() -> tuple[object | None, str]:
    """Import defensivo: instalacao quebrada levanta coisa que nao e ImportError
    (SyntaxError de .pyc velho, por exemplo) e nao pode matar a skill."""
    try:
        import feedparser  # type: ignore
        return feedparser, ""
    except ImportError as exc:
        return None, f"nao importou: {exc}"
    except Exception as exc:
        return None, f"importou e explodiu ({type(exc).__name__}: {exc})"


def _iso_de_struct(st) -> str | None:
    if not st:
        return None
    try:
        import calendar
        return datetime.fromtimestamp(calendar.timegm(st), timezone.utc).isoformat()
    except Exception:
        return None


def parsear_feedparser(mod, dados: bytes, resumo_max: int) -> tuple[dict, list[str]]:
    """Damos os BYTES que ja buscamos, nunca a URL.

    `feedparser.parse(url)` faria a propria requisicao, com o proprio
    tratamento de proxy e redirecionamento — segunda ida a rede, fora do
    controle desta skill e da promessa de canal direto."""
    d = mod.parse(dados)
    problemas: list[str] = []
    if getattr(d, "bozo", 0):
        problemas.append(f"feedparser marcou o documento como malformado: "
                         f"{type(getattr(d, 'bozo_exception', None)).__name__}")
    cab = getattr(d, "feed", {}) or {}
    cabecalho = {
        "titulo": limpar(cab.get("title")),
        "link": cab.get("link") or "",
        "descricao": limpar(cab.get("subtitle") or cab.get("description"), 300),
        "formato": getattr(d, "version", "") or "desconhecido",
    }
    itens = []
    for e in getattr(d, "entries", []) or []:
        resumo = e.get("summary") or ""
        if not resumo:
            conteudo = e.get("content") or []
            if conteudo:
                resumo = conteudo[0].get("value", "")
        data_bruta = e.get("published") or e.get("updated") or e.get("created") or ""
        itens.append({
            "titulo": limpar(e.get("title")) or None,
            "link": e.get("link") or None,
            "data": data_bruta or None,
            "data_iso": (_iso_de_struct(e.get("published_parsed") or e.get("updated_parsed"))
                         or _data_iso(data_bruta)),
            "resumo": limpar(resumo, resumo_max) or None,
            "id": e.get("id") or None,
            "autor": limpar(e.get("author"), 120) or None,
        })
    return {"feed": cabecalho, "itens": itens}, problemas


# --------------------------------------------------------------------------
# principal
# --------------------------------------------------------------------------

def executar(argumentos: dict) -> dict:
    url = str(argumentos.get("url") or argumentos.get("feed") or "").strip()
    limite = _inteiro(argumentos.get("limite"), LIMITE_ITENS_PADRAO, 1, LIMITE_ITENS_TETO)
    resumo_max = _inteiro(argumentos.get("resumo_max"), RESUMO_MAX_PADRAO, 40, 4000)
    timeout = _numero(argumentos.get("timeout"), TIMEOUT_PADRAO, 1.0, TIMEOUT_TETO)
    max_bytes = _inteiro(argumentos.get("max_bytes"), MAX_BYTES_PADRAO, 4096, 64 * 1024 * 1024)
    salvar_em = argumentos.get("salvar_em")
    forcar_degradado = bool(argumentos.get("forcar_degradado"))

    if not url:
        return {"ok": False, "skill": NOME_SKILL, "erro_categoria": "entrada",
                "erro": "faltou 'url': informe o endereco do feed RSS/Atom",
                "exemplo": {"url": "https://exemplo.org/feed.xml", "limite": 10},
                "itens": []}

    import os
    proxies_ignorados = sorted({v for v in VARS_PROXY if os.environ.get(v)})

    resposta, erro = buscar(url, timeout, max_bytes)
    if resposta is None:
        return {"ok": False, "skill": NOME_SKILL, "url_pedida": url,
                "erro_categoria": erro.get("categoria", "rede"),
                "erro": erro.get("mensagem", "falha desconhecida"),
                "status_http": erro.get("status"),
                "itens": []}

    problemas: list[str] = []
    if resposta.get("aviso"):
        problemas.append(resposta["aviso"])

    mod, motivo = (None, "modo degradado pedido por 'forcar_degradado'") \
        if forcar_degradado else carregar_feedparser()

    degradado = mod is None
    aviso_modo = None
    if degradado:
        aviso_modo = (
            f"MODO DEGRADADO: feedparser indisponivel ({motivo}). Usei xml.etree "
            "da stdlib. Cobre RSS 2.0, RSS 1.0/RDF e Atom nos campos comuns, mas "
            "NAO tem a tolerancia do feedparser a XML quebrado, nem deteccao de "
            "codificacao exotica, nem os campos estendidos (iTunes, media:*, "
            "geo). Atencao: o skill.json declara feedparser como requisito "
            "OBRIGATORIO, entao esta maquina esta fora do que o manifesto promete."
        )

    try:
        if degradado:
            cru, probs = parsear_degradado(resposta["bytes"])
            problemas.extend(probs)
            total = len(cru["itens_crus"])
            itens = [item_degradado(e, resumo_max) for e in cru["itens_crus"][:limite]]
            cabecalho = cru["feed"]
        else:
            cru, probs = parsear_feedparser(mod, resposta["bytes"], resumo_max)
            problemas.extend(probs)
            total = len(cru["itens"])
            itens = cru["itens"][:limite]
            cabecalho = cru["feed"]
    except Exception as exc:
        return {"ok": False, "skill": NOME_SKILL, "url_pedida": url,
                "url_final": resposta["url_final"],
                "erro_categoria": "parse",
                "erro": f"chegou resposta mas nao e um feed que eu saiba ler: "
                        f"{type(exc).__name__}: {exc}",
                "content_type": resposta["content_type"],
                "bytes_recebidos": resposta["bytes_recebidos"],
                "modo": "degradado_stdlib" if degradado else "feedparser",
                "aviso_modo": aviso_modo,
                "itens": []}

    # XML bem-formado NAO quer dizer feed. Uma pagina HTML servida como XHTML
    # atravessa o parser inteiro sem excecao e sairia com ok=true, feed vazio e
    # so um recado no meio da lista de problemas — verde falso, exatamente o
    # silencio que parece sucesso. Raiz nao reconhecida E zero itens = nao e
    # feed, e isso e falha. Raiz reconhecida com zero itens continua sucesso:
    # feed legitimamente vazio existe, e confundir os dois seria o erro oposto.
    formato = str(cabecalho.get("formato") or "")
    raiz_reconhecida = bool(formato) and not formato.startswith("desconhecido")
    if total == 0 and not raiz_reconhecida:
        return {"ok": False, "skill": NOME_SKILL, "url_pedida": url,
                "url_final": resposta["url_final"],
                "erro_categoria": "parse",
                "erro": (f"o documento e XML valido mas nao e um feed RSS/Atom "
                         f"(raiz/formato: {formato or 'indeterminado'}, zero itens)"),
                "content_type": resposta["content_type"],
                "bytes_recebidos": resposta["bytes_recebidos"],
                "modo": "degradado_stdlib" if degradado else "feedparser",
                "aviso_modo": aviso_modo,
                "problemas": problemas,
                "itens": []}
    if total == 0:
        problemas.append("feed reconhecido, porem sem nenhum item/entry no momento")

    escrita = {"pedida": bool(salvar_em), "ok": None, "caminho": None, "motivo": None}

    resultado = {
        "ok": True,
        "skill": NOME_SKILL,
        "url_pedida": url,
        "url_final": resposta["url_final"],
        "status_http": resposta["status"],
        "content_type": resposta["content_type"],
        "bytes_recebidos": resposta["bytes_recebidos"],
        "origem": {
            "host": urllib.parse.urlsplit(resposta["url_final"]).netloc,
            "direto_da_origem": True,
            "intermediario": None,
            "proxies_de_ambiente_ignorados": proxies_ignorados,
            "nota": "requisicao unica, sem proxy, sem servico de terceiro, "
                    "sem reescrita de URL: os bytes vieram do host acima",
        },
        "modo": "degradado_stdlib" if degradado else "feedparser",
        "modo_degradado": degradado,
        "aviso_modo": aviso_modo,
        "feed": cabecalho,
        "total_itens_no_feed": total,
        "itens_devolvidos": len(itens),
        "limite_aplicado": limite,
        "itens": itens,
        "problemas": problemas,
        "escrita": escrita,
    }

    if salvar_em:
        # Unica coisa que consome A1_WRITE_LOCAL, e so quando pedida por nome.
        try:
            from pathlib import Path
            destino = Path(str(salvar_em)).expanduser()
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(json.dumps(resultado, ensure_ascii=False, indent=2),
                               encoding="utf-8")
            escrita.update({"ok": True, "caminho": str(destino)})
        except Exception as exc:
            escrita.update({"ok": False, "motivo": f"{type(exc).__name__}: {exc}"})
            # A pessoa pediu para salvar e nao salvou: o trabalho falhou em
            # parte. Devolver ok=true com os itens na tela esconderia isso.
            resultado["ok"] = False
            problemas.append(f"nao consegui gravar em {salvar_em!r}: {escrita['motivo']}")

    return resultado


if __name__ == "__main__":
    args, erro_entrada = _ler_argumentos(sys.argv)
    if erro_entrada:
        print(json.dumps({"ok": False, "skill": NOME_SKILL,
                          "erro_categoria": "entrada", "erro": erro_entrada},
                         ensure_ascii=False))
        raise SystemExit(1)
    saida = executar(args)
    print(json.dumps(saida, ensure_ascii=False))
    raise SystemExit(0 if saida.get("ok") else 1)
