#!/usr/bin/env python3
"""citeguard-selfcheck — harness golden-master do verificador offline (46 casos).

O que este arquivo prova, e como
--------------------------------
Um golden master CONGELA o comportamento observado hoje e grita quando ele muda.
Ele não diz que o verificador está CERTO — diz que continua fazendo o que fazia.
Por isso os casos abaixo incluem, de propósito, quatro comportamentos que são
DEFEITO (grupo X). Congelá-los é o que faz o alarme tocar no dia em que alguém
os consertar (aí o harness precisa ser recalibrado) — e mantê-los VISÍVEIS na
saída é o que impede alguém de ler "46/46 PASS" como "o verificador é correto".

Por que a lógica está EMBUTIDA em vez de importada da skill irmã
----------------------------------------------------------------
Duas razões, nesta ordem:

1. PERMISSÃO. O manifesto declara só A0_READ_LOCAL e A1_WRITE_LOCAL. Importar
   `verify_offline.py` da skill vizinha é executar código de fora do diretório
   desta skill — isso é A5_CODE_EXEC, que NÃO está declarado. Uma skill não pode
   fazer mais do que seu manifesto promete, nem "só para testar".
2. CERCA DO SANDBOX. A execução governada roda com deny-default fora do workdir;
   depender do caminho do disco do dono produz uma skill que instala e não roda.

A ponte entre o porte embutido e o original é feita por SHA-256, não por import:
lemos o arquivo da irmã como TEXTO (isso é A0, leitura local) e conferimos o
digest contra `SHA256_IRMA_CALIBRADO`. Se bater, o porte abaixo é fiel ao que
está no disco. Se não bater, o harness ficou obsoleto e o veredito é FAIL —
recalibrar é ato humano. Se a irmã não estiver acessível, dizemos INACESSIVEL em
vez de deixar o silêncio parecer confirmação.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# PORTE VERBATIM de citeguard-verify-offline/verify_offline.py
# Calibrado contra o digest abaixo. NÃO "melhore" nada aqui: qualquer divergência
# em relação ao original transforma este harness num teste de si mesmo, que é
# exatamente o tipo de teste que não detecta regressão nenhuma.
# ---------------------------------------------------------------------------
SHA256_IRMA_CALIBRADO = \
    "b38b353290a4eb652ef260b86d507295f019470de9f8bb23b9de0caf9d3c326c"
NOME_IRMA = "citeguard-verify-offline"
ARQUIVO_IRMA = "verify_offline.py"

DOI = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b")
DOI_PLACEHOLDER = re.compile(r"\b10\.(?:x{4,}|0{4}|1234|nnnn)\S*", re.I)
ARXIV = re.compile(r"\barXiv:\s*(\d{4}\.\d{4,5})(v\d+)?\b", re.I)
URL = re.compile(r"https?://[^\s<>\"')\]]+")
PLACEHOLDER = ("example.com", "example.org", "localhost", "foo.bar",
               "your-domain", "TODO", "FIXME", "XXXX")


def _host_privado(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host in ("localhost",) or host.endswith(".local")
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


def verificar(texto: str) -> dict:
    achados: list[dict] = []

    def falha(tipo, alvo, motivo):
        achados.append({"nivel": "FAIL", "tipo": tipo, "alvo": alvo, "motivo": motivo})

    for m in DOI_PLACEHOLDER.finditer(texto):
        falha("doi", m.group(0), "placeholder de DOI (10.xxxx/10.0000/10.1234)")
    for m in DOI.finditer(texto):
        doi = m.group(0)
        if doi.rstrip("._;()/").endswith(("/", ".")):
            falha("doi", doi, "sufixo truncado")
    for m in ARXIV.finditer(texto):
        num = m.group(1)
        aa, mm = num.split(".")[0][:2], num.split(".")[0][2:]
        if not ("01" <= mm <= "12"):
            falha("arxiv", m.group(0), f"mês inválido no id: {mm}")
    for m in URL.finditer(texto):
        u = m.group(0)
        host = (urlparse(u).hostname or "").lower()
        if any(p.lower() in u.lower() for p in PLACEHOLDER):
            falha("url", u, "placeholder, não é fonte real")
        elif host and _host_privado(host):
            falha("url", u, "host privado/loopback — inalcançável para quem lê")

    n_doi = len(set(DOI.findall(texto)))
    n_arxiv = len(set(x[0] for x in ARXIV.findall(texto)))
    return {
        "citacoes_encontradas": {"doi": n_doi, "arxiv": n_arxiv,
                                 "url": len(set(URL.findall(texto)))},
        "falhas": achados,
        "veredito": "FAIL" if achados else "PASS",
        "limite_declarado": ("modo OFFLINE: não confirma existência do DOI nem "
                             "retratação — isso exige rede"),
    }


# ---------------------------------------------------------------------------
# OS 46 CASOS
#
# `cit` é [doi, arxiv, url] — a contagem DEDUPLICADA que o verificador reporta.
# `tipos` vem ORDENADO: a ordem em que as falhas são anexadas é detalhe de
# implementação (varre placeholder-DOI, depois DOI, depois arXiv, depois URL) e
# congelá-la faria o harness reprovar por uma refatoração inofensiva.
# Cada expectativa foi derivada lendo o original e depois CONFERIDA rodando —
# nenhuma foi copiada da saída sem antes ter sido prevista.
# ---------------------------------------------------------------------------
def _ok(cit, tipos=()):
    return {"veredito": "PASS", "n_falhas": 0, "tipos": list(tipos), "cit": list(cit)}


def _mau(n, tipos, cit):
    return {"veredito": "FAIL", "n_falhas": n, "tipos": sorted(tipos), "cit": list(cit)}


CASOS: list[dict] = [
    # -- grupo A: texto limpo, tem de passar ---------------------------------
    {"id": "A01", "grupo": "limpo", "desc": "entrada vazia",
     "texto": "", "esperado": _ok([0, 0, 0])},
    {"id": "A02", "grupo": "limpo", "desc": "prosa sem nenhuma citacao",
     "texto": "Nenhuma referencia aqui, apenas texto corrido.",
     "esperado": _ok([0, 0, 0])},
    {"id": "A03", "grupo": "limpo", "desc": "DOI bem formado",
     "texto": "Ver DOI 10.1038/nature12373 para detalhes.",
     "esperado": _ok([1, 0, 0])},
    {"id": "A04", "grupo": "limpo", "desc": "arXiv id bem formado",
     "texto": "arXiv:1706.03762", "esperado": _ok([0, 1, 0])},
    {"id": "A05", "grupo": "limpo", "desc": "URL publica em https",
     "texto": "https://arxiv.org/abs/1706.03762", "esperado": _ok([0, 0, 1])},
    {"id": "A06", "grupo": "limpo", "desc": "citacao completa: DOI + arXiv + URL",
     "texto": ("Vaswani et al. arXiv:1706.03762 DOI 10.48550/arXiv.1706.03762 "
               "https://arxiv.org/abs/1706.03762"),
     "esperado": _ok([1, 1, 1])},
    {"id": "A07", "grupo": "limpo", "desc": "mes 01 e o limite INFERIOR valido",
     "texto": "arXiv:2001.00001", "esperado": _ok([0, 1, 0])},
    {"id": "A08", "grupo": "limpo", "desc": "mes 12 e o limite SUPERIOR valido",
     "texto": "arXiv:2012.99999", "esperado": _ok([0, 1, 0])},
    {"id": "A09", "grupo": "limpo", "desc": "IP publico nao e host privado",
     "texto": "http://8.8.8.8/paper.pdf", "esperado": _ok([0, 0, 1])},
    {"id": "A10", "grupo": "limpo", "desc": "DOI com parenteses no sufixo (estilo Wiley)",
     "texto": "10.1002/(SICI)1097-0258", "esperado": _ok([1, 0, 0])},

    # -- grupo N: contagem e deduplicacao ------------------------------------
    {"id": "N01", "grupo": "contagem", "desc": "dois DOIs distintos contam 2",
     "texto": "Compare 10.1038/nature12373 com 10.1126/science.1259855 nos resultados.",
     "esperado": _ok([2, 0, 0])},
    {"id": "N02", "grupo": "contagem",
     "desc": "mesmo arXiv em v1 e v2 conta 1 (dedup ignora a versao)",
     "texto": "arXiv:1706.03762v1 arXiv:1706.03762v2", "esperado": _ok([0, 1, 0])},

    # -- grupo B: placeholder de DOI -----------------------------------------
    {"id": "B01", "grupo": "doi-placeholder", "desc": "10.xxxx",
     "texto": "10.xxxx/fake", "esperado": _mau(1, ["doi"], [0, 0, 0])},
    {"id": "B02", "grupo": "doi-placeholder",
     "desc": "10.0000 casa nos DOIS padroes (placeholder e DOI): 1 falha, cit doi=1",
     "texto": "10.0000/placeholder", "esperado": _mau(1, ["doi"], [1, 0, 0])},
    {"id": "B03", "grupo": "doi-placeholder", "desc": "10.1234",
     "texto": "10.1234/fake-doi", "esperado": _mau(1, ["doi"], [1, 0, 0])},
    {"id": "B04", "grupo": "doi-placeholder", "desc": "10.nnnn",
     "texto": "10.nnnn/unknown", "esperado": _mau(1, ["doi"], [0, 0, 0])},
    {"id": "B05", "grupo": "doi-placeholder", "desc": "MAIUSCULAS (regex e re.I)",
     "texto": "10.XXXX/FAKE", "esperado": _mau(1, ["doi"], [0, 0, 0])},
    {"id": "B06", "grupo": "doi-placeholder", "desc": "dois placeholders = duas falhas",
     "texto": "10.xxxx/a e 10.nnnn/b", "esperado": _mau(2, ["doi", "doi"], [0, 0, 0])},

    # -- grupo C: placeholder dentro de URL ----------------------------------
    # Os 8 termos de PLACEHOLDER estao cobertos entre C01..C07 e X02.
    {"id": "C01", "grupo": "url-placeholder", "desc": "example.com",
     "texto": "https://example.com/paper", "esperado": _mau(1, ["url"], [0, 0, 1])},
    {"id": "C02", "grupo": "url-placeholder", "desc": "example.org",
     "texto": "https://example.org/ref", "esperado": _mau(1, ["url"], [0, 0, 1])},
    {"id": "C03", "grupo": "url-placeholder", "desc": "your-domain",
     "texto": "https://your-domain.com/x", "esperado": _mau(1, ["url"], [0, 0, 1])},
    {"id": "C04", "grupo": "url-placeholder", "desc": "foo.bar",
     "texto": "https://foo.bar/baz", "esperado": _mau(1, ["url"], [0, 0, 1])},
    {"id": "C05", "grupo": "url-placeholder",
     "desc": "localhost cai como PLACEHOLDER, nao como host privado (ordem do if)",
     "texto": "http://localhost:8080/doc", "esperado": _mau(1, ["url"], [0, 0, 1]),
     "motivo_esperado": "placeholder, não é fonte real"},
    {"id": "C06", "grupo": "url-placeholder",
     "desc": "dois gatilhos na MESMA url (example.com + FIXME) contam 1 falha",
     "texto": "https://git.example.com/FIXME", "esperado": _mau(1, ["url"], [0, 0, 1])},
    {"id": "C07", "grupo": "url-placeholder", "desc": "XXXX",
     "texto": "https://cdn.exemplo.net/redacted-XXXX.pdf",
     "esperado": _mau(1, ["url"], [0, 0, 1])},

    # -- grupo D: host privado / loopback / link-local -----------------------
    {"id": "D01", "grupo": "host-privado", "desc": "loopback 127.0.0.1",
     "texto": "http://127.0.0.1:8000/paper", "esperado": _mau(1, ["url"], [0, 0, 1]),
     "motivo_esperado": "host privado/loopback — inalcançável para quem lê"},
    {"id": "D02", "grupo": "host-privado", "desc": "RFC1918 192.168/16",
     "texto": "http://192.168.1.10/artigo.pdf", "esperado": _mau(1, ["url"], [0, 0, 1])},
    {"id": "D03", "grupo": "host-privado",
     "desc": "RFC1918 10/8 — e '10.0.0.5' NAO e confundido com DOI",
     "texto": "http://10.0.0.5/ref", "esperado": _mau(1, ["url"], [0, 0, 1])},
    {"id": "D04", "grupo": "host-privado", "desc": "link-local 169.254/16",
     "texto": "http://169.254.10.1/x", "esperado": _mau(1, ["url"], [0, 0, 1])},
    {"id": "D05", "grupo": "host-privado", "desc": "0.0.0.0 (this-network)",
     "texto": "http://0.0.0.0/x", "esperado": _mau(1, ["url"], [0, 0, 1])},
    {"id": "D06", "grupo": "host-privado", "desc": "mDNS .local",
     "texto": "http://meumac.local/paper.pdf", "esperado": _mau(1, ["url"], [0, 0, 1])},

    # -- grupo E: mes invalido no id do arXiv --------------------------------
    {"id": "E01", "grupo": "arxiv-mes", "desc": "mes 13 (acima do limite)",
     "texto": "arXiv:2413.00001", "esperado": _mau(1, ["arxiv"], [0, 1, 0]),
     "motivo_esperado": "mês inválido no id: 13"},
    {"id": "E02", "grupo": "arxiv-mes", "desc": "mes 00 (abaixo do limite)",
     "texto": "arXiv:2400.12345", "esperado": _mau(1, ["arxiv"], [0, 1, 0]),
     "motivo_esperado": "mês inválido no id: 00"},
    {"id": "E03", "grupo": "arxiv-mes", "desc": "ARXIV maiusculo ainda casa",
     "texto": "ARXIV:2413.00001", "esperado": _mau(1, ["arxiv"], [0, 1, 0])},
    {"id": "E04", "grupo": "arxiv-mes", "desc": "espaco depois dos dois-pontos",
     "texto": "arXiv: 2413.00001", "esperado": _mau(1, ["arxiv"], [0, 1, 0])},

    # -- grupo M: mistos, varios tipos no mesmo texto ------------------------
    {"id": "M01", "grupo": "misto", "desc": "arXiv invalido + loopback",
     "texto": "arXiv:2413.00001 e http://127.0.0.1/p",
     "esperado": _mau(2, ["arxiv", "url"], [0, 1, 1])},
    {"id": "M02", "grupo": "misto", "desc": "os tres tipos de falha juntos",
     "texto": "10.xxxx/a arXiv:2413.00002 http://localhost/x",
     "esperado": _mau(3, ["arxiv", "doi", "url"], [0, 1, 1])},
    {"id": "M03", "grupo": "misto",
     "desc": "bibliografia realista: 1 boa, 2 ruins — as boas nao viram falha",
     "texto": ("Ref1 10.1038/nature12373. Ref2 arXiv:2413.00003. "
               "Ref3 https://example.com/p"),
     "esperado": _mau(2, ["arxiv", "url"], [1, 1, 1])},

    # -- grupo F: CONTROLE — o que se PARECE com falha e nao e ---------------
    # Sem este grupo o harness nao provaria que o verificador discrimina: um
    # verificador que reprovasse tudo passaria em A..E inteiro.
    {"id": "F01", "grupo": "controle",
     "desc": "ftp:// nao e http(s) — regex de URL nao pega, loopback passa batido",
     "texto": "ftp://127.0.0.1/x", "esperado": _ok([0, 0, 0])},
    {"id": "F02", "grupo": "controle",
     "desc": "'localhost' em prosa, fora de URL, nao dispara nada",
     "texto": "O servidor localhost nao e citacao.", "esperado": _ok([0, 0, 0])},
    {"id": "F03", "grupo": "controle", "desc": "10.123 tem 3 digitos, DOI exige 4+",
     "texto": "10.123/abc", "esperado": _ok([0, 0, 0])},
    {"id": "F04", "grupo": "controle", "desc": "sufixo arXiv de 3 digitos nao casa",
     "texto": "arXiv:2401.123", "esperado": _ok([0, 0, 0])},

    # -- grupo X: DEFEITOS CONHECIDOS, congelados de proposito ---------------
    # Estes casos passam quando o verificador ERRA. Estao aqui para que o erro
    # seja documentado e vigiado, nunca para dar a impressao de que esta certo.
    # A saida os republica em `defeitos_conhecidos` a cada execucao.
    {"id": "X01", "grupo": "defeito",
     "desc": "FALSO POSITIVO: DOI legitimo com prefixo 10.1234x vira 'placeholder'",
     "texto": "10.12345/abc", "esperado": _mau(1, ["doi"], [1, 0, 0]),
     "defeito": ("DOI_PLACEHOLDER usa \\b10\\.1234\\S* sem ancora de fim, entao "
                 "qualquer DOI do prefixo 10.1234x (10.12345, 10.12349...) e "
                 "acusado de falso. Registrante 10.12345 existe de verdade.")},
    {"id": "X02", "grupo": "defeito",
     "desc": "FALSO POSITIVO: 'TODO' e casado como SUBSTRING em qualquer lugar da URL",
     "texto": "https://revista.org/artigos/todos-os-numeros",
     "esperado": _mau(1, ["url"], [0, 0, 1]),
     "defeito": ("a checagem e `p.lower() in u.lower()`, sem fronteira de palavra: "
                 "'todos', 'metodo', 'fixmesh' e afins caem como placeholder.")},
    {"id": "X03", "grupo": "defeito",
     "desc": "CRASH: URL com IPv6 entre colchetes levanta ValueError nao tratado",
     "texto": "http://[::1]:9000/paper",
     "esperado": {"veredito": "EXCECAO", "excecao": "ValueError"},
     "defeito": ("a regex de URL exclui ']', entao casa 'http://[::1' truncado; "
                 "urlparse recusa IPv6 sem fechar colchete e o ValueError sobe ate "
                 "o topo — o verificador MORRE em vez de reprovar a citacao. Um "
                 "relatorio com loopback IPv6 derruba o gate inteiro.")},
    {"id": "X04", "grupo": "defeito",
     "desc": "LACUNA: multicast 224/4 nao e classificado como inalcancavel",
     "texto": "http://224.0.0.1/x", "esperado": _ok([0, 0, 1]),
     "defeito": ("_host_privado olha private/loopback/link_local/reserved; "
                 "multicast nao entra em nenhum deles e uma URL multicast, "
                 "que nenhum leitor alcanca, e aprovada.")},
]

# Defeito estrutural que NAO da para expressar como caso, porque nao ha entrada
# que o dispare — e esse e exatamente o ponto. Vai declarado na saida.
DEFEITOS_SEM_CASO = [
    {"onde": "verificar(), ramo 'sufixo truncado'",
     "defeito": ("codigo morto: `doi.rstrip('._;()/').endswith(('/', '.'))` nunca "
                 "e verdadeiro, porque o rstrip acabou de remover '/' e '.' do fim. "
                 "Alem disso o \\b final da regex DOI ja impede capturar esse sufixo. "
                 "Conclusao: DOI truncado NAO e detectado por ninguem."),
     "verificado_em": ["10.1234/abc/", "10.5555/abc.", "10.5555/abc", "10.5555/x;"]},
]


# ---------------------------------------------------------------------------
# execucao dos casos
# ---------------------------------------------------------------------------
def _obter(texto: str) -> dict:
    """Roda o porte e normaliza o resultado para a forma comparavel.

    A excecao e CAPTURADA e vira um veredito de primeira classe ("EXCECAO") em
    vez de derrubar o harness: um caso que quebra o verificador e informacao,
    e um harness que morre no caso 43 nao reporta os outros 3.
    """
    try:
        r = verificar(texto)
    except Exception as exc:
        return {"veredito": "EXCECAO", "excecao": type(exc).__name__,
                "mensagem": str(exc)[:200]}
    c = r["citacoes_encontradas"]
    return {"veredito": r["veredito"],
            "n_falhas": len(r["falhas"]),
            "tipos": sorted(f["tipo"] for f in r["falhas"]),
            "cit": [c["doi"], c["arxiv"], c["url"]],
            "motivos": [f["motivo"] for f in r["falhas"]]}


def _rodar_caso(caso: dict) -> dict:
    obtido = _obter(caso["texto"])
    esperado = caso["esperado"]
    # Comparacao PARCIAL de proposito: so as chaves que o caso declara. Assim o
    # caso X03 cobra apenas veredito+excecao, sem inventar n_falhas para algo
    # que nunca chegou a produzir falhas.
    recorte = {k: obtido.get(k) for k in esperado}
    divergencias = {k: {"esperado": esperado[k], "obtido": recorte[k]}
                    for k in esperado if recorte[k] != esperado[k]}
    if not divergencias and "motivo_esperado" in caso:
        if caso["motivo_esperado"] not in obtido.get("motivos", []):
            divergencias["motivo"] = {"esperado": caso["motivo_esperado"],
                                      "obtido": obtido.get("motivos", [])}
    return {"id": caso["id"], "grupo": caso["grupo"], "desc": caso["desc"],
            "resultado": "PASS" if not divergencias else "FAIL",
            "divergencias": divergencias, "obtido": obtido}


# ---------------------------------------------------------------------------
# paridade com a skill irma (por digest, sem executar nada dela)
# ---------------------------------------------------------------------------
def _paridade_irma() -> dict:
    """Confere o SHA-256 do original. Caminho RELATIVO a esta skill, de proposito.

    Estados possiveis, todos explicitos:
      CONFIRMADA  — o porte embutido corresponde ao arquivo no disco;
      DIVERGENTE  — a irma mudou; o harness esta obsoleto (=> FAIL);
      INACESSIVEL — a cerca do sandbox ou a ausencia do arquivo impediram a
                    leitura. NAO e falha do harness, mas tambem NAO e confirmacao.
    """
    alvo = Path(__file__).resolve().parent.parent / NOME_IRMA / ARQUIVO_IRMA
    base = {"caminho_tentado": str(alvo),
            "sha256_calibrado": SHA256_IRMA_CALIBRADO}
    try:
        bruto = alvo.read_bytes()
    except OSError as exc:
        return {**base, "estado": "INACESSIVEL", "sha256_encontrado": None,
                "detalhe": (f"nao consegui ler o original ({type(exc).__name__}). "
                            "A paridade do porte embutido com a skill irma NAO foi "
                            "verificada nesta execucao.")}
    achado = hashlib.sha256(bruto).hexdigest()
    if achado == SHA256_IRMA_CALIBRADO:
        return {**base, "estado": "CONFIRMADA", "sha256_encontrado": achado,
                "detalhe": "o porte embutido corresponde ao verificador no disco"}
    return {**base, "estado": "DIVERGENTE", "sha256_encontrado": achado,
            "detalhe": ("o verificador MUDOU desde a calibracao: os 46 casos "
                        "descrevem a versao antiga e nao provam nada sobre a atual. "
                        "Recalibrar (reler o original, refazer as expectativas, "
                        "atualizar SHA256_IRMA_CALIBRADO) e ato humano.")}


# ---------------------------------------------------------------------------
# entrada / saida
# ---------------------------------------------------------------------------
def _ler_args(argv: list[str]) -> dict:
    """argv[1] e um caminho para JSON (e como a execucao governada chama).

    Sem argumento o default e o unico sensato para um autoteste: rodar tudo.
    Aceita tambem JSON inline, para uso manual no terminal.
    """
    if len(argv) <= 1:
        return {}
    bruto = argv[1]
    try:
        return json.loads(Path(bruto).read_text(encoding="utf-8"))
    except OSError:
        pass
    except ValueError:
        return {}
    try:
        dado = json.loads(bruto)
        return dado if isinstance(dado, dict) else {}
    except ValueError:
        return {}


def main(argv: list[str]) -> int:
    args = _ler_args(argv)
    verboso = bool(args.get("verboso", False))
    filtro = str(args.get("grupo", "") or "").strip().lower()

    selecionados = [c for c in CASOS
                    if not filtro or c["grupo"].lower() == filtro
                    or c["id"].lower().startswith(filtro)]

    resultados = [_rodar_caso(c) for c in selecionados]
    falhos = [r for r in resultados if r["resultado"] == "FAIL"]
    paridade = _paridade_irma()

    # Um caso que passa NAO apaga o defeito que ele congela: republicamos os
    # defeitos a cada execucao para que "46/46" nunca seja lido como "correto".
    defeitos = [{"id": c["id"], "desc": c["desc"], "defeito": c["defeito"]}
                for c in selecionados if "defeito" in c]

    # Ordem das causas importa: casos reprovados dizem que o comportamento MUDOU;
    # divergencia de digest diz que o harness envelheceu. Sao coisas diferentes.
    if falhos:
        veredito, rc = "FAIL", 1
        motivo = f"{len(falhos)} caso(s) divergiram do golden master"
    elif paridade["estado"] == "DIVERGENTE":
        veredito, rc = "FAIL", 2
        motivo = "todos os casos passaram, mas o verificador mudou: harness obsoleto"
    else:
        veredito, rc = "PASS", 0
        motivo = "comportamento identico ao congelado"

    saida = {
        "skill": "citeguard-selfcheck",
        "modo": "golden-master offline",
        "veredito": veredito,
        "motivo": motivo,
        "total": len(selecionados),
        "passaram": len(selecionados) - len(falhos),
        "falharam": len(falhos),
        "por_grupo": {g: {
            "total": sum(1 for r in resultados if r["grupo"] == g),
            "falharam": sum(1 for r in falhos if r["grupo"] == g)}
            for g in sorted({r["grupo"] for r in resultados})},
        "casos": [{"id": r["id"], "grupo": r["grupo"], "resultado": r["resultado"],
                   "desc": r["desc"]} for r in resultados],
        "casos_falhos": falhos,
        "paridade_irma": paridade,
        "defeitos_conhecidos": defeitos,
        "defeitos_sem_caso": DEFEITOS_SEM_CASO,
        "rede": "nao usada: nenhum socket e aberto; o harness e integralmente offline",
        "permissoes_usadas": ["A0_READ_LOCAL (digest da skill irma)"],
        "limites_declarados": [
            "NAO importa nem executa verify_offline.py: isso seria A5_CODE_EXEC, "
            "que este manifesto nao declara. A fidelidade do porte embutido e "
            "estabelecida por SHA-256, nao por execucao.",
            "golden master CONGELA o comportamento atual, inclusive os 4 defeitos "
            "do grupo X e o codigo morto listado em defeitos_sem_caso. "
            "PASS significa 'nao mudou', jamais 'esta correto'.",
            "paridade INACESSIVEL nao e aprovacao: significa que nao deu para "
            "conferir se o porte ainda corresponde ao original.",
            "cobre so o verificador OFFLINE. Nada aqui testa existencia de DOI, "
            "retratacao, citeguard-verify-online ou citeguard-retractions-sync — "
            "essas dependem de rede e ficam fora por desenho.",
        ],
    }
    if verboso:
        saida["casos"] = resultados

    destino = args.get("relatorio")
    if destino:
        # A0+A1 permitem escrever local. Falha de escrita e REPORTADA, nunca
        # engolida: um relatorio que nao existe nao pode virar prova de nada.
        try:
            p = Path(str(destino))
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(saida, ensure_ascii=False, indent=2),
                         encoding="utf-8")
            saida["relatorio_escrito"] = str(p)
        except OSError as exc:
            saida["relatorio_escrito"] = None
            saida["relatorio_erro"] = f"{type(exc).__name__}: {exc}"
            if rc == 0:
                veredito, rc = "FAIL", 3
                saida["veredito"] = veredito
                saida["motivo"] = ("casos passaram, mas o relatorio pedido nao "
                                   "pode ser escrito")

    print(json.dumps(saida, ensure_ascii=False, indent=2))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
