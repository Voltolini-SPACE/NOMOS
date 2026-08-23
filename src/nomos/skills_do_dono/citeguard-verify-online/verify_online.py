"""citeguard-verify-online — confirma EXISTÊNCIA de DOI/arXiv consultando terceiros.

Complemento do `citeguard-verify-offline`: aquele prova FORMA (malformado,
placeholder, host privado) sem tocar a rede; este prova EXISTÊNCIA, e para isso
precisa perguntar a alguém de fora. O preço é declarado na saída, não escondido:
cada DOI e cada arXiv id encontrado no seu texto SAI DESTA MÁQUINA.

Só stdlib. Não importa o `citeguard.py` do dono nem nenhum caminho do disco
dele: a cerca do sandbox só enxerga o workdir, então uma skill que dependesse
disso instalaria e não rodaria. O preço é duplicar ~40 linhas de regex; o
benefício é ser instalável de verdade.

Fronteira honesta desta skill:
  - prova: o identificador resolve numa autoridade pública (Crossref/arXiv);
  - prova: retratação, quando há índice local do Retraction Watch OU quando o
    próprio Crossref marca `update-to: retraction`;
  - NÃO prova: que o trabalho diz o que a citação afirma que ele diz;
  - NÃO prova: ausência do DOI no mundo — só ausência NO CROSSREF (ver ressalva
    de agência de registro em `_consultar_doi`).
Falha de rede NUNCA vira "não existe". Essa é a regra central do arquivo: um
timeout que virasse veredito reprovaria bibliografia honesta por causa de Wi-Fi.
"""
from __future__ import annotations

import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

VERSAO = "1.0.0"

# Sem `mailto:` de propósito. O "polite pool" do Crossref pede e-mail e dá cota
# melhor; mandar o e-mail do dono junto de TODA bibliografia dele é vigilância
# barata em troca de vazão. Ficamos na fila anônima e dizemos isso na saída.
UA = f"nomos-citeguard-verify-online/{VERSAO}"

# Único conjunto de hosts que esta skill pode contatar. É reconferido a CADA hop
# de redirect: sem isso, um 302 do Crossref apontando para 169.254.169.254
# transformaria o verificador em leitor de metadados de nuvem (SSRF).
HOSTS_PERMITIDOS = ("api.crossref.org", "export.arxiv.org")


class _SemRedirect(urllib.request.HTTPRedirectHandler):
    """Devolve o 3xx como HTTPError em vez de segui-lo.

    Seguir redirect automaticamente delegaria ao servidor remoto a escolha do
    próximo host. Aqui o salto é feito à mão em `_abrir`, revalidando a
    allowlist antes de cada conexão.
    """

    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(_SemRedirect)

# arXiv "novo" exige mês 01-12 no id. Sem essa amarra, `\d{4}\.\d{4,5}` casa
# preço, versão de software e número de tabela — e a skill sairia para a rede
# perguntando por lixo, vazando o texto do relatório em pedaços.
ARXIV_NOVO = re.compile(r"\b(?:arxiv:\s*)?(\d{2}(?:0[1-9]|1[0-2])\.\d{4,5})(?:v\d+)?\b", re.I)
ARXIV_ANTIGO = re.compile(r"\b([a-z][a-z-]+(?:\.[A-Z]{2})?/\d{7})\b")
# O sufixo do DOI aceita parêntese — existe de verdade: 10.1016/S0140-6736(97)11096-0.
DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"'<>\]}]+", re.I)


def normalizar_doi(bruto: str) -> str:
    """Reduz as várias grafias de DOI à forma canônica minúscula `10.x/y`."""
    d = (bruto or "").strip().lower()
    for pref in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/",
                 "http://dx.doi.org/", "doi.org/", "doi:"):
        if d.startswith(pref):
            d = d[len(pref):]
            break
    # Pontuação final pertence à frase, não ao DOI. O `)` só cai se estiver
    # desbalanceado — senão quebraríamos o DOI do Lancet citado acima.
    d = d.strip().rstrip(".,;")
    while d.endswith(")") and d.count("(") < d.count(")"):
        d = d[:-1]
    return d


def _titulo_diz_retratado(titulo) -> bool:
    """Crossref muitas vezes só sinaliza retratação renomeando o título."""
    if not titulo:
        return False
    t = str(titulo).strip().upper()
    return t.startswith("RETRACTED") or t.startswith("WITHDRAWN") or "(RETRACTED ARTICLE" in t


def extrair(texto: str) -> list:
    """DOIs e arXiv ids do texto, deduplicados pelo id canônico.

    Deduplicar aqui é privacidade, não só desempenho: o mesmo DOI citado 12
    vezes viraria 12 idas ao Crossref.
    """
    achados = []
    vistos = set()

    def add(tipo, bruto, ident):
        chave = tipo + ":" + ident
        if chave in vistos:
            return
        vistos.add(chave)
        achados.append({"tipo": tipo, "id": ident, "bruto": bruto.strip()})

    for m in DOI_RE.finditer(texto):
        nd = normalizar_doi(m.group(0))
        if nd:
            add("doi", m.group(0), nd)
    for m in ARXIV_NOVO.finditer(texto):
        add("arxiv", m.group(0), m.group(1).lower())
    for m in ARXIV_ANTIGO.finditer(texto):
        add("arxiv", m.group(0), m.group(1))
    return achados


def carregar_retratados(caminhos: list) -> dict:
    """Índice local de DOIs retratados (formato do `citeguard-retractions-sync`:
    um DOI normalizado por linha).

    Sem ele a retratação ainda é detectada, porém SÓ pelo que o Crossref
    admitir — cobertura menor. A saída diz qual dos dois casos ocorreu, para
    que "nenhum retratado" não seja lido como prova quando foi só ignorância.
    """
    for c in caminhos:
        if not c:
            continue
        try:
            with open(os.path.expanduser(c), encoding="utf-8") as fh:
                dois = {ln.strip().lower() for ln in fh if ln.strip()}
        except OSError:
            continue  # inexistente ou barrado pela cerca do sandbox: tenta o próximo
        return {"disponivel": True, "origem": os.path.expanduser(c),
                "dois_indexados": len(dois), "_set": dois}
    return {
        "disponivel": False, "origem": None, "dois_indexados": 0, "_set": set(),
        "nota": ("nenhum indice local de retratacao encontrado; RETRATADO so sera "
                 "detectado se o proprio Crossref marcar. Rode a skill "
                 "citeguard-retractions-sync para fechar essa lacuna."),
    }


def _host_de(url: str) -> str:
    return (urllib.parse.urlparse(url).hostname or "").lower()


def _abrir(url: str, timeout: float, accept=None):
    """GET com allowlist de host revalidada a CADA redirect."""
    for _ in range(4):
        if _host_de(url) not in HOSTS_PERMITIDOS:
            raise OSError("host fora da allowlist desta skill: " + repr(_host_de(url)))
        cab = {"User-Agent": UA}
        if accept:
            cab["Accept"] = accept
        try:
            resp = _OPENER.open(urllib.request.Request(url, headers=cab), timeout=timeout)
            return resp.status, resp.read(4_000_000).decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            loc = e.headers.get("Location") if e.headers else None
            if e.code in (301, 302, 303, 307, 308) and loc:
                url = urllib.parse.urljoin(url, loc)
                continue
            raise
    raise OSError("redirects demais")


def _consultar_doi(doi: str, timeout: float, retratados: set) -> dict:
    """Resolve um DOI já normalizado."""
    # Camada 0 é OFFLINE e autoritativa: se o índice local já sabe que está
    # retratado, não há por que entregar esse DOI ao Crossref também.
    if doi in retratados:
        return {"estado": "EXISTE", "retratado": True, "titulo": None,
                "fonte": "indice local retraction-watch",
                "detalhe": "retratado segundo indice local; NAO foi consultado online",
                "saiu_da_maquina": False}

    # Um DOI casado por regex é texto de terceiro entrando numa URL. `..` no
    # sufixo permitiria andar para fora de /works/ dentro da API; recusamos em
    # vez de encodar e torcer.
    if ".." in doi:
        return {"estado": "NAO_CONSULTADO", "retratado": None, "titulo": None,
                "fonte": None,
                "detalhe": "DOI contem '..' (travessia de caminho) — recusado sem sair da maquina",
                "saiu_da_maquina": False}

    # `safe="/"` preserva a barra que estrutura o DOI e neutraliza `? # & %` e
    # espaço, que senão virariam query string ou fragmento.
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="/")
    try:
        _st, corpo = _abrir(url, timeout, accept="application/json")
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            return {
                "estado": "NAO_EXISTE", "retratado": None, "titulo": None,
                "fonte": "api.crossref.org", "detalhe": "http " + str(e.code),
                "saiu_da_maquina": True,
                "ressalva": ("ausente NO CROSSREF. DOI registrado por outra agencia "
                             "(DataCite/Zenodo 10.5281, mEDRA, ...) tambem responde 404 "
                             "aqui sem ser forjado — confira a agencia antes de acusar."),
            }
        # 429 e 5xx dizem respeito ao servidor, não ao DOI.
        return {"estado": "ERRO_DE_REDE", "retratado": None, "titulo": None,
                "fonte": "api.crossref.org", "detalhe": "http " + str(e.code),
                "saiu_da_maquina": True}
    except (urllib.error.URLError, OSError, socket.timeout) as e:
        return {"estado": "ERRO_DE_REDE", "retratado": None, "titulo": None,
                "fonte": "api.crossref.org",
                "detalhe": type(e).__name__ + ": " + str(e), "saiu_da_maquina": True}

    try:
        msg = json.loads(corpo).get("message", {})
    except ValueError as e:
        return {"estado": "ERRO_DE_REDE", "retratado": None, "titulo": None,
                "fonte": "api.crossref.org", "detalhe": "resposta ilegivel: " + str(e),
                "saiu_da_maquina": True}
    titulo = (msg.get("title") or [None])[0]
    tipos_update = [u.get("type") for u in (msg.get("update-to") or [])]
    retratado = "retraction" in tipos_update or _titulo_diz_retratado(titulo)
    return {"estado": "EXISTE", "retratado": retratado, "titulo": titulo,
            "fonte": "api.crossref.org",
            "detalhe": "crossref: retratado" if retratado else "crossref ok",
            "saiu_da_maquina": True}


def _consultar_arxiv(aid: str, timeout: float) -> dict:
    url = ("https://export.arxiv.org/api/query?id_list="
           + urllib.parse.quote(aid, safe="") + "&max_results=1")
    try:
        _st, corpo = _abrir(url, timeout)
    except urllib.error.HTTPError as e:
        # O arXiv devolve 400 para id sintaticamente impossível: isso é veredito
        # sobre o id, não sobre a rede.
        if e.code == 400:
            return {"estado": "NAO_EXISTE", "retratado": None, "titulo": None,
                    "fonte": "export.arxiv.org", "detalhe": "http 400: id invalido",
                    "saiu_da_maquina": True}
        return {"estado": "ERRO_DE_REDE", "retratado": None, "titulo": None,
                "fonte": "export.arxiv.org", "detalhe": "http " + str(e.code),
                "saiu_da_maquina": True}
    except (urllib.error.URLError, OSError, socket.timeout) as e:
        return {"estado": "ERRO_DE_REDE", "retratado": None, "titulo": None,
                "fonte": "export.arxiv.org",
                "detalhe": type(e).__name__ + ": " + str(e), "saiu_da_maquina": True}

    # O arXiv responde 200 mesmo para id inexistente; o sinal canônico é
    # totalResults, e o reserva é a entry de título "Error".
    tr = re.search(r"<opensearch:totalResults[^>]*>(\d+)<", corpo)
    if tr and tr.group(1) == "0":
        return {"estado": "NAO_EXISTE", "retratado": None, "titulo": None,
                "fonte": "export.arxiv.org", "detalhe": "totalResults=0",
                "saiu_da_maquina": True}
    m = re.search(r"<entry>.*?<title>(.*?)</title>", corpo, re.S)
    titulo = re.sub(r"\s+", " ", m.group(1)).strip() if m else None
    if titulo and titulo.lower() != "error":
        # O arXiv não tem campo de retratação; "withdrawn" aparece no título.
        return {"estado": "EXISTE", "retratado": _titulo_diz_retratado(titulo),
                "titulo": titulo, "fonte": "export.arxiv.org",
                "detalhe": "arxiv api", "saiu_da_maquina": True}
    return {"estado": "NAO_EXISTE", "retratado": None, "titulo": None,
            "fonte": "export.arxiv.org", "detalhe": "entry Error / sem titulo",
            "saiu_da_maquina": True}


def verificar(texto: str, timeout: float = 8.0, max_consultas: int = 50,
              intervalo_s: float = 0.2, caminhos_retratados=None) -> dict:
    idx = carregar_retratados(caminhos_retratados or [])
    set_retratados = idx.pop("_set")
    citacoes = extrair(texto)

    resultados = []
    enviados = []
    nao_consultadas = []
    for c in citacoes:
        if len(enviados) >= max_consultas and c["id"] not in set_retratados:
            # Teto explícito, e a sobra aparece na saída. Truncar em silêncio
            # produziria um "0 falhas" que só significa "parei de olhar".
            nao_consultadas.append(c)
            continue
        if intervalo_s > 0 and resultados and resultados[-1].get("saiu_da_maquina"):
            time.sleep(intervalo_s)  # cortesia com API pública e gratuita
        if c["tipo"] == "doi":
            r = _consultar_doi(c["id"], timeout, set_retratados)
        else:
            r = _consultar_arxiv(c["id"], timeout)
        if r.get("saiu_da_maquina"):
            enviados.append(c["tipo"] + ":" + c["id"])
        item = dict(c)
        item.update(r)
        resultados.append(item)

    n = {"EXISTE": 0, "NAO_EXISTE": 0, "ERRO_DE_REDE": 0, "NAO_CONSULTADO": 0}
    for r in resultados:
        n[r["estado"]] = n.get(r["estado"], 0) + 1
    retratadas = [r for r in resultados if r.get("retratado")]

    # Três vereditos, não dois: "não consegui verificar" não é aprovação nem
    # reprovação, e achatá-lo em qualquer um dos dois seria mentir.
    if not citacoes:
        veredito = "SEM_CITACOES"
    elif n["NAO_EXISTE"] or retratadas:
        veredito = "REPROVADO"
    elif n["ERRO_DE_REDE"] or n["NAO_CONSULTADO"] or nao_consultadas:
        veredito = "INCONCLUSIVO"
    else:
        veredito = "APROVADO"

    resumo = dict(n)
    resumo["retratadas"] = len(retratadas)
    resumo["citacoes_encontradas"] = len(citacoes)
    resumo["nao_consultadas_por_teto"] = len(nao_consultadas)

    return {
        "skill": "citeguard-verify-online",
        "versao": VERSAO,
        "veredito": veredito,
        "resumo": resumo,
        "citacoes": resultados,
        "nao_consultadas_por_teto": nao_consultadas,
        "indice_retratacao": idx,
        "privacidade": {
            "aviso": ("CADA DOI E CADA arXiv id listado em 'identificadores_enviados' "
                      "SAIU DESTA MAQUINA para um terceiro. Quem opera esses servicos "
                      "pode registrar o que voce esta lendo, quando, e de qual IP."),
            "destinos": ["https://api.crossref.org (recebe o DOI)",
                         "https://export.arxiv.org (recebe o arXiv id)"],
            "identificadores_enviados": enviados,
            "consultas_http": len(enviados),
            "nao_enviado": ("o texto do relatorio, o nome/caminho do arquivo, o trecho "
                            "em volta da citacao e o seu e-mail"),
            "identificacao": "User-Agent " + repr(UA) + "; sem mailto, sem chave, sem cookie",
        },
        "limites_declarados": [
            "confirma que o identificador RESOLVE; nao confirma que o trabalho "
            "sustenta a afirmacao citada",
            "NAO_EXISTE de DOI significa ausente no Crossref — DOI de outra agencia "
            "de registro (DataCite, mEDRA) responde 404 sem ser forjado",
            "ERRO_DE_REDE nunca vira NAO_EXISTE: falta de rede nao e prova de nada",
            "sem indice local do Retraction Watch, RETRATADO depende do Crossref admitir",
            "nao verifica URL solta nem placeholder — isso e do citeguard-verify-offline",
        ],
    }


def _carregar_entrada(argv: list):
    """Devolve (texto, args, erro). Aceita args.json, caminho solto ou stdin."""
    args = {}
    if len(argv) > 1:
        bruto = argv[1]
        try:
            with open(bruto, encoding="utf-8", errors="replace") as fh:
                conteudo = fh.read()
        except OSError as e:
            return "", {}, "nao consegui ler " + repr(bruto) + ": " + str(e)
        try:
            carregado = json.loads(conteudo)
        except ValueError:
            # Não era args.json: o próprio arquivo é o relatório a verificar.
            return conteudo, {}, None
        if not isinstance(carregado, dict):
            return conteudo, {}, None
        args = carregado
        if args.get("arquivo"):
            try:
                with open(os.path.expanduser(args["arquivo"]), encoding="utf-8",
                          errors="replace") as fh:
                    return fh.read(), args, None
            except OSError as e:
                return "", args, "arquivo indicado nos args nao pode ser lido: " + str(e)
        if args.get("texto") is not None:
            return str(args["texto"]), args, None
        return "", args, "args.json sem 'arquivo' nem 'texto'"
    return sys.stdin.read(), {}, None


def main(argv: list) -> int:
    texto, args, erro = _carregar_entrada(argv)
    if erro:
        print(json.dumps({"skill": "citeguard-verify-online",
                          "veredito": "ERRO_DE_ENTRADA", "erro": erro},
                         ensure_ascii=False, indent=2))
        return 3

    caminhos = [args.get("retratados"), "retracted_dois.txt",
                "~/.citeguard/retracted_dois.txt"]
    rel = verificar(
        texto,
        timeout=float(args.get("timeout", 8.0)),
        max_consultas=int(args.get("max_consultas", 50)),
        intervalo_s=float(args.get("intervalo_s", 0.2)),
        caminhos_retratados=[c for c in caminhos if c],
    )

    if args.get("saida"):
        # Único uso de A1_WRITE_LOCAL, e só quando pedido explicitamente.
        try:
            destino = os.path.expanduser(args["saida"])
            with open(destino, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(rel, ensure_ascii=False, indent=2) + "\n")
            rel["relatorio_gravado_em"] = destino
        except OSError as e:
            rel["relatorio_nao_gravado"] = type(e).__name__ + ": " + str(e)
    print(json.dumps(rel, ensure_ascii=False, indent=2))

    return {"REPROVADO": 1, "INCONCLUSIVO": 2}.get(rel["veredito"], 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
