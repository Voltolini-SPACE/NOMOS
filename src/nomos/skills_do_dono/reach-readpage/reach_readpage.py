"""Skill oficial: reach-readpage — le uma pagina web via r.jina.ai (A1_WRITE_LOCAL + A2_NET_EGRESS).

AVISO QUE DEFINE ESTA SKILL: r.jina.ai e um servico de TERCEIROS. Ler uma pagina
por aqui significa ENTREGAR A URL para esse terceiro, que pode registra-la junto
com o IP de saida desta maquina. Foi essa diferenca que justificou separar esta
skill das outras skills de leitura — logo o aviso nao pode ser rodape opcional:
`aviso_terceiro` sai em TODA resposta, inclusive nas de erro, e o booleano
`enviado_a_terceiro` diz sem rodeio se a URL ja vazou ou ainda nao.

Por que urllib e nao `curl`, mesmo com `requires: {binario: curl}` no manifesto:
chamar `curl` seria subprocess, ou seja execucao de programa externo, e o
manifesto declara apenas A1_WRITE_LOCAL e A2_NET_EGRESS — A5_CODE_EXEC NAO esta
declarada. O `requires` e uma checagem de instalacao (`shutil.which`), nao uma
autorizacao para gastar permissao que a skill nao tem. urllib tambem sobrevive ao
sandbox de PATH curto (/usr/local/bin:/usr/bin:/bin), onde nada de /opt/homebrew
existe.
"""
import hashlib
import ipaddress
import json
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

TERCEIRO_HOST = "r.jina.ai"
TERCEIRO_BASE = "https://r.jina.ai/"
TERCEIRO_OPERADOR = "Jina AI"
AVISO_TERCEIRO = (
    "ATENCAO: esta skill NAO le a pagina direto. Ela pede a leitura ao servico de "
    "TERCEIROS r.jina.ai (Jina AI). A URL inteira — dominio, caminho e query — sai "
    "desta maquina para esse terceiro, que pode registra-la, junto com o IP de saida "
    "e o horario. Nao use para URL privada, assinada ou com token embutido."
)

MAX_BYTES_PADRAO = 200_000
MAX_BYTES_TETO = 5_000_000
TIMEOUT_PADRAO = 25
TIMEOUT_TETO = 120

# Nomes de parametro que costumam carregar segredo. Mandar isso a um terceiro
# equivale a vazar credencial, entao aqui vira recusa (com escape explicito),
# nao um aviso que ninguem le depois que o dado ja saiu.
_QUERY_SENSIVEL = re.compile(
    r"(token|api[-_]?key|apikey|secret|senha|password|passwd|signature|^sig$|"
    r"auth|bearer|session|credential|access)", re.IGNORECASE)

_SUFIXOS_INTERNOS = (".local", ".internal", ".lan", ".intranet", ".home.arpa")


def _agora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _envelope(ok, enviado, extra):
    """Toda saida — sucesso ou erro — carrega o bloco do terceiro.

    Montado num lugar so justamente para que nenhum caminho de retorno consiga
    'esquecer' o aviso: quem esquece e quem repete o campo em N returns.
    """
    saida = {
        "ok": bool(ok),
        "skill": "reach-readpage",
        "quando": _agora(),
        "enviado_a_terceiro": bool(enviado),
        "aviso_terceiro": AVISO_TERCEIRO,
        "terceiro": {
            "host": TERCEIRO_HOST,
            "operador": TERCEIRO_OPERADOR,
            "o_que_ele_recebe": "a URL completa (dominio, caminho e query), o IP de "
                                "saida desta maquina e o horario do pedido",
            "url_ja_enviada": bool(enviado),
        },
    }
    saida.update(extra)
    return saida


def _motivo_host_inalcancavel(host):
    """Host interno? Recusa: o terceiro nao alcanca E o nome interno vazaria a toa."""
    h = (host or "").strip().lower().rstrip(".")
    if not h:
        return "URL sem host"
    try:
        ip = ipaddress.ip_address(h.strip("[]"))
    except ValueError:
        ip = None
    if ip is not None:
        if (ip.is_loopback or ip.is_private or ip.is_link_local
                or ip.is_reserved or ip.is_unspecified):
            return (f"{h} e endereco de rede interna/local: r.jina.ai nao alcanca, "
                    "e mandar isso so vazaria a topologia da sua rede")
        return None
    if h == "localhost" or h.endswith(_SUFIXOS_INTERNOS) or "." not in h:
        return (f"host {h!r} so resolve dentro desta rede: r.jina.ai nao alcanca, "
                "e mandar isso so vazaria nome interno")
    return None


def _analisar_url(bruta, permitir_query_sensivel):
    """(url_normalizada, problema). Nada sai da maquina antes de passar por aqui."""
    if not isinstance(bruta, str) or not bruta.strip():
        return None, ("informe 'url' (http:// ou https://) — nao ha default: "
                      "chutar uma URL aqui significaria entregar algo a um terceiro "
                      "sem ninguem ter pedido")
    bruta = bruta.strip()
    p = urllib.parse.urlsplit(bruta)
    if p.scheme.lower() not in ("http", "https"):
        return None, (f"esquema {p.scheme or '(vazio)'!r} nao suportado: r.jina.ai le "
                      "so http/https (file:, data: e ftp: nao passam por aqui)")
    if p.username or p.password:
        return None, ("a URL traz usuario/senha embutidos (user:senha@host). Isso "
                      "seria credencial entregue a um terceiro — recusado, e nada "
                      "foi enviado")
    motivo = _motivo_host_inalcancavel(p.hostname)
    if motivo:
        return None, motivo
    if p.query:
        chaves = [k for k, _ in urllib.parse.parse_qsl(p.query, keep_blank_values=True)]
        suspeitas = sorted({k for k in chaves if _QUERY_SENSIVEL.search(k)})
        if suspeitas and not permitir_query_sensivel:
            return None, ("a query carrega parametro com cara de segredo "
                          f"({', '.join(suspeitas)}) e ele iria inteiro para "
                          "r.jina.ai. Recusado; nada foi enviado. Se for mesmo "
                          "publico, repita com permitir_query_sensivel=true")
    return bruta, None


def _percent_encode(url):
    """Escapa so o que quebraria o pedido (espaco, acento) e preserva a sintaxe.

    quote() padrao escaparia ':' e '/', o que transformaria a URL alvo em lixo,
    porque ela viaja como CAMINHO dentro de https://r.jina.ai/<url>.
    """
    return urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~._-")


def _texto_da_resposta(resp, max_bytes):
    # Le max_bytes+1 para conseguir DIZER que truncou em vez de entregar um
    # pedaco fingindo ser a pagina inteira.
    bruto = resp.read(max_bytes + 1)
    truncado = len(bruto) > max_bytes
    if truncado:
        bruto = bruto[:max_bytes]
    try:
        charset = resp.headers.get_content_charset()
    except Exception:
        charset = None
    texto = bruto.decode(charset or "utf-8", errors="replace")
    return texto, truncado, len(bruto)


def _titulo(texto):
    """r.jina.ai devolve um cabecalho 'Title: ...'. So aproveita se existir."""
    primeira = texto.split("\n", 1)[0].strip()
    return primeira[7:].strip() if primeira.startswith("Title: ") else None


def _salvar(caminho, texto):
    """Uso concreto de A1_WRITE_LOCAL. Falha de escrita nao apaga a leitura:
    vira campo de erro, porque o texto ja chegou e ja custou o envio da URL."""
    try:
        with open(caminho, "w", encoding="utf-8") as fh:
            fh.write(texto)
        return {"caminho": caminho, "escrito": True,
                "bytes": len(texto.encode("utf-8"))}
    except OSError as exc:
        return {"caminho": caminho, "escrito": False,
                "erro": f"{type(exc).__name__}: {exc}"}


def _erro_http(exc, url, alvo):
    try:
        corpo = exc.read(400).decode("utf-8", errors="replace").strip()
    except Exception:
        corpo = ""
    dica = None
    if exc.code in (401, 402, 429):
        # Honestidade: chave paga resolveria, mas A3_CRED_USE nao esta declarada
        # no manifesto — esta skill NAO pode ler o cofre nem mandar Authorization.
        dica = ("limite do acesso anonimo do r.jina.ai. Esta skill nao envia chave: "
                "o manifesto nao declara permissao de credencial. Espere e tente de "
                "novo, ou use outra rota de leitura")
    elif exc.code in (403, 404, 410, 451):
        dica = "o terceiro falou com o site, mas o site recusou ou nao tem a pagina"
    elif exc.code >= 500:
        dica = "falha do lado do r.jina.ai — nada a corrigir do lado de ca"
    return _envelope(False, True, {
        "url_solicitada": url,
        "url_no_terceiro": alvo,
        "erro": f"HTTP {exc.code} de {TERCEIRO_HOST}",
        "erro_tipo": "http",
        "http_status": exc.code,
        "corpo_do_erro": corpo[:400],
        "dica": dica,
        "texto": None,
    })


def executar(argumentos):
    args = argumentos if isinstance(argumentos, dict) else {}
    url_bruta = args.get("url")
    permitir = bool(args.get("permitir_query_sensivel", False))

    url, problema = _analisar_url(url_bruta, permitir)
    if problema:
        # enviado_a_terceiro=False aqui NAO e detalhe: prova que a recusa
        # aconteceu antes de qualquer byte sair da maquina.
        return _envelope(False, False, {
            "url_solicitada": url_bruta if isinstance(url_bruta, str) else None,
            "erro": problema,
            "erro_tipo": "entrada",
            "texto": None,
        })

    try:
        max_bytes = int(args.get("max_bytes", MAX_BYTES_PADRAO))
        timeout = float(args.get("timeout", TIMEOUT_PADRAO))
    except (TypeError, ValueError):
        return _envelope(False, False, {
            "url_solicitada": url,
            "erro": "max_bytes e timeout precisam ser numeros",
            "erro_tipo": "entrada",
            "texto": None,
        })
    max_bytes = max(1_000, min(max_bytes, MAX_BYTES_TETO))
    timeout = max(1.0, min(timeout, TIMEOUT_TETO))

    alvo = TERCEIRO_BASE + _percent_encode(url)
    pedido = urllib.request.Request(alvo, headers={
        "Accept": "text/plain",
        "User-Agent": "nomos-reach-readpage/1.0",
    })
    try:
        with urllib.request.urlopen(pedido, timeout=timeout) as resp:
            texto, truncado, lidos = _texto_da_resposta(resp, max_bytes)
            status = getattr(resp, "status", None) or resp.getcode()
            tipo = resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        return _erro_http(exc, url, alvo)
    except urllib.error.URLError as exc:
        # Se o DNS nem resolveu, nada trafegou de fato. Distinguir isso importa:
        # e a diferenca entre "vazou" e "nao vazou", que e a razao desta skill.
        causa = getattr(exc, "reason", exc)
        dns_morto = isinstance(causa, socket.gaierror)
        return _envelope(False, not dns_morto, {
            "url_solicitada": url,
            "url_no_terceiro": alvo,
            "erro": f"nao consegui falar com {TERCEIRO_HOST}: {causa}",
            "erro_tipo": "rede_indisponivel" if dns_morto else "rede",
            "dica": ("sem DNS/rede nesta maquina ou sandbox sem egresso — a skill "
                     "exige internet e nao tem modo offline" if dns_morto else
                     "conexao iniciada e interrompida; a URL pode ter chegado ao terceiro"),
            "texto": None,
        })
    except socket.timeout:
        return _envelope(False, True, {
            "url_solicitada": url,
            "url_no_terceiro": alvo,
            "erro": f"estourou o timeout de {timeout:.0f}s esperando {TERCEIRO_HOST}",
            "erro_tipo": "timeout",
            "dica": "a URL JA foi enviada ao terceiro; so a resposta nao voltou a tempo",
            "texto": None,
        })
    except Exception as exc:
        return _envelope(False, True, {
            "url_solicitada": url,
            "url_no_terceiro": alvo,
            "erro": f"falha inesperada: {type(exc).__name__}: {exc}",
            "erro_tipo": "inesperado",
            "texto": None,
        })

    if not texto.strip():
        return _envelope(False, True, {
            "url_solicitada": url,
            "url_no_terceiro": alvo,
            "http_status": status,
            "erro": "r.jina.ai respondeu 200 com corpo VAZIO",
            "erro_tipo": "vazio",
            "dica": "pagina renderizada por JS, bloqueio de bot ou paywall",
            "texto": None,
        })

    escrita = None
    salvar_em = args.get("salvar_em")
    if isinstance(salvar_em, str) and salvar_em.strip():
        escrita = _salvar(salvar_em.strip(), texto)

    return _envelope(True, True, {
        "url_solicitada": url,
        "url_no_terceiro": alvo,
        "http_status": status,
        "content_type": tipo,
        "titulo": _titulo(texto),
        "texto": texto,
        "caracteres": len(texto),
        "bytes_lidos": lidos,
        "truncado": truncado,
        "sha256_texto": hashlib.sha256(texto.encode("utf-8")).hexdigest(),
        "escrita_local": escrita,
        "limites": [
            "o texto vem do r.jina.ai, nao do site: e a leitura DELE, ja convertida",
            ("corte em max_bytes=%d" % max_bytes) + (" — ESTE resultado foi truncado"
                                                     if truncado else " (nao truncou)"),
            "sem chave de API: sujeito ao limite anonimo do servico",
        ],
    })


def _ler_argumentos(argv):
    """Arquivo JSON no argv[1]; senao stdin; senao dicionario vazio.

    Vazio nao vira default silencioso: `executar` recusa sem url, porque um
    default aqui significaria contatar um terceiro sem ninguem ter pedido.
    """
    if len(argv) > 1:
        with open(argv[1], encoding="utf-8") as fh:
            return json.load(fh)
    if not sys.stdin.isatty():
        bruto = sys.stdin.read().strip()
        if bruto:
            return json.loads(bruto)
    return {}


if __name__ == "__main__":
    try:
        _args = _ler_argumentos(sys.argv)
    except (OSError, ValueError) as _exc:
        print(json.dumps(_envelope(False, False, {
            "erro": f"nao consegui ler os argumentos: {type(_exc).__name__}: {_exc}",
            "erro_tipo": "entrada",
            "texto": None,
        }), ensure_ascii=False))
        sys.exit(1)
    _res = executar(_args)
    print(json.dumps(_res, ensure_ascii=False))
    sys.exit(0 if _res.get("ok") else 1)
