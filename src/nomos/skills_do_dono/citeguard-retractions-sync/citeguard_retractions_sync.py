#!/usr/bin/env python3
"""citeguard-retractions-sync — baixa o índice de retratações do Retraction Watch.

Por que esta skill existe: sem o índice local, o citeguard não consegue afirmar
que uma citação foi RETRATADA — ele degrada para WARN. Um paper retirado saindo
como WARN é exatamente o erro que o citeguard existe para impedir, então este
arquivo é pré-condição do veredito FAIL, não um extra.

Postura, e o motivo de cada uma (o porquê de cada guarda está no ponto de uso):

  * STREAMING. O CSV tem ~66 MB. A implementação de referência faz `r.read()` e
    depois `.decode()`, o que mantém os 66 MB crus e a str decodificada vivos ao
    mesmo tempo. Aqui o corpo desce em blocos para um temporário em disco e o
    CSV é lido de volta em fluxo, então o pico de memória não acompanha o
    tamanho do arquivo.

  * FAIL-CLOSED. Qualquer dúvida sobre completude NÃO grava arquivo. Um
    `retracted_dois.txt` truncado é PIOR que nenhum: o consumidor não tem como
    distinguir "este DOI não está retratado" de "meu índice parou na metade", e
    a ausência vira aprovação silenciosa. Por isso o destino só passa a existir
    depois que o download inteiro foi conferido, e via os.replace (atômico).

  * STDOUT É SÓ JSON. Progresso vai para stderr; quem faz parse do stdout não
    pode receber texto solto no meio.

Permissões declaradas no manifesto: A1_WRITE_LOCAL + A2_NET_EGRESS. Nada além
disso — não lê o disco do dono fora do próprio args.json, não executa binário
externo, não depende de nada fora da stdlib.
"""
from __future__ import annotations

import csv
import ipaddress
import json
import os
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

# Espelho oficial do Retraction Watch mantido pela Crossref (CC0). É a mesma URL
# que o citeguard.py usa; divergir aqui produziria dois índices diferentes com o
# mesmo nome de arquivo, que é a pior forma de erro possível neste contexto.
URL_PADRAO = "https://gitlab.com/crossref/retraction-watch-data/-/raw/main/retraction_watch.csv"

DESTINO_PADRAO = "retracted_dois.txt"

# ~66 MB hoje. O teto é folga para crescimento, não meta: existe para que um
# redirect para algo gigante não encha o disco do dono em silêncio.
LIMITE_BYTES_PADRAO = 256 * 1024 * 1024
TIMEOUT_PADRAO = 60          # por operação de socket
DEADLINE_PADRAO = 900        # relógio de parede do download inteiro

# Piso de sanidade. A base real tem dezenas de milhares de DOIs; colher poucas
# centenas significa que o parse pegou a coluna errada ou que a origem devolveu
# outra coisa com HTTP 200. Gravar assim mesmo produziria um índice que aprova
# quase tudo — falha silenciosa exatamente no caminho crítico.
MINIMO_DOIS_PADRAO = 1000

BLOCO = 1 << 16

# Campos como "Notes" e "Reason" do Retraction Watch passam com folga do limite
# default do módulo csv (131072) e o parse morreria no meio da base real.
csv.field_size_limit(8 * 1024 * 1024)

PREFIXOS_DOI = ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/",
                "http://dx.doi.org/", "doi.org/", "doi:")
NAO_DOI = {"", "unavailable", "n/a", "na", "none", "null", "0", "-"}


class Falha(Exception):
    """Erro previsto, com tipo estável para quem consome o JSON."""

    def __init__(self, tipo: str, detalhe: str, codigo: int = 1):
        super().__init__(detalhe)
        self.tipo, self.detalhe, self.codigo = tipo, detalhe, codigo


def normalizar_doi(bruto: str) -> str:
    """Mesma normalização do citeguard.py.

    Precisa ser idêntica, não só parecida: o consumidor compara por igualdade
    exata de string. Um índice normalizado de outro jeito não dá erro — ele
    simplesmente nunca casa, e toda retratação vira "não retratado".
    """
    d = (bruto or "").strip().lower()
    for p in PREFIXOS_DOI:
        if d.startswith(p):
            d = d[len(p):]
            break
    return d.strip().rstrip(".,;")


def _host_publico(host: str) -> bool:
    """False para loopback/privado/link-local/reservado (inclusive via DNS)."""
    if not host:
        return False
    candidatos: list[str] = []
    try:
        ipaddress.ip_address(host)
        candidatos = [host]
    except ValueError:
        if host == "localhost" or host.endswith(".local"):
            return False
        try:
            candidatos = [i[4][0] for i in socket.getaddrinfo(host, None)]
        except OSError:
            return False          # não resolve: fail-closed, não "deixa passar"
    for c in candidatos:
        try:
            ip = ipaddress.ip_address(c)
        except ValueError:
            return False
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved \
                or ip.is_multicast or ip.is_unspecified:
            return False
    return bool(candidatos)


def validar_url(url: str) -> None:
    """A URL é parâmetro, logo é superfície de ataque.

    Sem esta checagem, apontar a skill para http://169.254.169.254/... converte
    uma permissão de "baixar uma lista pública" em leitura de metadados de
    nuvem, sem que o manifesto mude uma linha.

    Isto é um piso, NÃO uma prova: resolvemos o nome aqui e o urllib resolve de
    novo ao conectar, então um DNS que muda entre os dois momentos escapa
    (TOCTOU). Dito em voz alta para ninguém confundir com sandbox de rede.
    """
    p = urlparse(url)
    if p.scheme != "https":
        raise Falha("url_recusada",
                    f"só https é aceito (recebido: {p.scheme or 'sem esquema'!r})", 2)
    if not _host_publico((p.hostname or "").lower()):
        raise Falha("url_recusada",
                    f"host não público ou irresolúvel: {p.hostname!r}", 2)


def baixar(url: str, destino_tmp: str, limite: int, timeout: float,
           deadline: float) -> dict:
    """Escoa o corpo para disco em blocos. Devolve o que dá para PROVAR sobre ele."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "nomos-citeguard-retractions-sync/1.0 (+stdlib urllib)",
        # Pedimos identity de propósito: com gzip o Content-Length descreve o
        # corpo comprimido e a comparação com os bytes escritos deixaria de
        # significar "baixei tudo", que é a única prova de completude que temos.
        "Accept-Encoding": "identity",
    })
    inicio = time.monotonic()
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        raise Falha("http", f"origem respondeu HTTP {e.code} {e.reason}", 1) from e
    except urllib.error.URLError as e:
        raise Falha("rede", f"não foi possível alcançar a origem: {e.reason}", 1) from e
    except (TimeoutError, socket.timeout) as e:
        raise Falha("timeout", f"timeout de {timeout}s ao conectar", 1) from e

    with resp:
        cabecalhos = resp.headers
        esperado = cabecalhos.get("Content-Length")
        esperado = int(esperado) if (esperado or "").isdigit() else None
        codificacao = (cabecalhos.get("Content-Encoding") or "identity").lower()
        if esperado is not None and esperado > limite:
            raise Falha("limite_excedido",
                        f"origem anuncia {esperado} bytes, acima do limite de "
                        f"{limite}; nada foi gravado", 1)
        lidos = 0
        with open(destino_tmp, "wb") as saida:
            while True:
                if time.monotonic() - inicio > deadline:
                    raise Falha("timeout",
                                f"download passou do prazo de {deadline}s com "
                                f"{lidos} bytes; descartado", 1)
                try:
                    bloco = resp.read(BLOCO)
                except (TimeoutError, socket.timeout) as e:
                    raise Falha("timeout",
                                f"fluxo parou por mais de {timeout}s após "
                                f"{lidos} bytes", 1) from e
                except (urllib.error.URLError, OSError, EOFError) as e:
                    # http.client.IncompleteRead cai aqui: é uma conexão cortada
                    # no meio, ou seja, download comprovadamente parcial.
                    raise Falha("download_incompleto",
                                f"fluxo interrompido após {lidos} bytes: {e}", 1) from e
                if not bloco:
                    break
                lidos += len(bloco)
                if lidos > limite:
                    raise Falha("limite_excedido",
                                f"corpo passou do limite de {limite} bytes; "
                                f"download abortado e descartado", 1)
                saida.write(bloco)

    if codificacao != "identity":
        # Não sabemos comparar bytes crus com corpo transformado; em vez de
        # inventar uma conclusão, recusamos.
        raise Falha("codificacao_inesperada",
                    f"origem devolveu Content-Encoding={codificacao!r}, que "
                    f"impede conferir completude por tamanho", 1)
    if esperado is not None and lidos != esperado:
        raise Falha("download_incompleto",
                    f"esperados {esperado} bytes, recebidos {lidos}", 1)
    if lidos == 0:
        raise Falha("resposta_vazia", "origem devolveu corpo de 0 byte", 1)

    return {
        "url": url,
        "bytes_baixados": lidos,
        "bytes_esperados": esperado,
        "completude": ("conferida por Content-Length" if esperado is not None
                       else "SEM Content-Length: só sabemos que o fluxo terminou "
                            "sem corte; a garantia é mais fraca"),
        "segundos": round(time.monotonic() - inicio, 2),
    }


def extrair_dois(caminho_csv: str, coluna_pedida: str | None) -> dict:
    """Colhe os DOIs dos artigos retratados.

    Usamos OriginalPaperDOI (o DOI do artigo que foi retirado) e NÃO
    RetractionDOI: este segundo é o DOI do AVISO de retratação, cuja citação é
    legítima. Misturar os dois faria o citeguard reprovar quem cita a
    retratação corretamente — falso positivo no gate.
    """
    with open(caminho_csv, encoding="utf-8", errors="replace", newline="") as fh:
        leitor = csv.DictReader(fh)
        campos = leitor.fieldnames or []
        if coluna_pedida:
            coluna = next((c for c in campos if c == coluna_pedida), None)
            if coluna is None:
                raise Falha("coluna_ausente",
                            f"coluna {coluna_pedida!r} não existe; disponíveis: {campos}", 2)
        else:
            coluna = next((c for c in campos
                           if c and c.replace(" ", "").lower() == "originalpaperdoi"), None)
        if coluna is None:
            raise Falha("coluna_ausente",
                        f"não achei OriginalPaperDOI no cabeçalho: {campos}", 2)

        dois: set[str] = set()
        linhas = descartadas = 0
        for linha in leitor:
            linhas += 1
            d = normalizar_doi(linha.get(coluna) or "")
            # Forma mínima de DOI. Sem isto, marcadores como "unavailable"
            # entrariam no índice e o consumidor compararia contra lixo.
            if d in NAO_DOI or not d.startswith("10.") or "/" not in d:
                descartadas += 1
                continue
            dois.add(d)
    return {"dois": dois, "linhas_lidas": linhas, "descartadas": descartadas,
            "coluna_usada": coluna, "colunas_disponiveis": campos}


def gravar(destino: str, dois: set[str]) -> str:
    """Grava ordenado e ATÔMICO: temporário no mesmo diretório + os.replace.

    O temporário fica no mesmo diretório porque os.replace só é atômico dentro
    do mesmo sistema de arquivos. Assim o destino nunca é observado pela metade:
    ou é o índice anterior, ou é o novo inteiro.
    """
    destino = os.path.abspath(os.path.expanduser(destino))
    pasta = os.path.dirname(destino) or "."
    try:
        os.makedirs(pasta, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=pasta, prefix=".retracted_dois.", suffix=".parcial")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write("\n".join(sorted(dois)))
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())   # sem isto um corte de energia deixa o
                                        # nome final apontando para conteúdo vazio
            os.replace(tmp, destino)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError as e:
        raise Falha("escrita_negada", f"não consegui gravar em {destino}: {e}", 2) from e
    return destino


LIMITES = [
    "cobre apenas OriginalPaperDOI (artigo retratado); o DOI do AVISO de "
    "retratação fica de fora de propósito, porque citá-lo é legítimo",
    "é uma FOTO do dia: retratação publicada depois desta execução não está no "
    "arquivo — reexecute periodicamente",
    "não cobre retratação de artigo sem DOI, nem expression of concern",
    "não valida a origem por assinatura: confia no TLS do GitLab/Crossref",
]


def executar(args: dict) -> dict:
    url = args.get("url") or URL_PADRAO
    destino = args.get("destino") or DESTINO_PADRAO
    limite = int(args.get("limite_bytes") or LIMITE_BYTES_PADRAO)
    timeout = float(args.get("timeout_s") or TIMEOUT_PADRAO)
    deadline = float(args.get("deadline_s") or DEADLINE_PADRAO)
    minimo = int(args.get("minimo_dois", MINIMO_DOIS_PADRAO))

    validar_url(url)

    fd, cru = tempfile.mkstemp(prefix="rw_csv_", suffix=".csv")
    os.close(fd)
    try:
        fonte = baixar(url, cru, limite, timeout, deadline)
        sys.stderr.write(f"[sync] baixados {fonte['bytes_baixados']} bytes\n")
        colhido = extrair_dois(cru, args.get("coluna"))
    finally:
        # O CSV cru é insumo, não entrega: some sempre, inclusive em falha.
        try:
            os.unlink(cru)
        except OSError:
            pass

    dois = colhido["dois"]
    if len(dois) < minimo:
        raise Falha("abaixo_do_piso",
                    f"só {len(dois)} DOIs válidos (piso {minimo}). Índice raso "
                    f"aprovaria citação retratada, então NADA foi gravado", 2)

    caminho = gravar(destino, dois)
    return {
        "ok": True,
        "arquivo_gravado": True,
        "destino": caminho,
        "dois_gravados": len(dois),
        "fonte": fonte,
        "csv": {"linhas_lidas": colhido["linhas_lidas"],
                "descartadas": colhido["descartadas"],
                "coluna_usada": colhido["coluna_usada"]},
        "erro": None,
        "limites_declarados": LIMITES,
    }


def carregar_args(argv: list[str]) -> dict:
    """`python3 entry args.json`; sem argumento, stdin; sem stdin, defaults."""
    if len(argv) > 1:
        try:
            with open(argv[1], encoding="utf-8") as fh:
                dados = json.load(fh)
        except (OSError, ValueError) as e:
            raise Falha("args_invalidos", f"não li {argv[1]!r} como JSON: {e}", 2) from e
        if not isinstance(dados, dict):
            raise Falha("args_invalidos", "o JSON de argumentos precisa ser um objeto", 2)
        return dados
    if not sys.stdin.isatty():
        bruto = sys.stdin.read().strip()
        if bruto:
            try:
                dados = json.loads(bruto)
            except ValueError as e:
                raise Falha("args_invalidos", f"stdin não é JSON: {e}", 2) from e
            if not isinstance(dados, dict):
                raise Falha("args_invalidos", "o JSON de argumentos precisa ser um objeto", 2)
            return dados
    return {}


def main(argv: list[str]) -> int:
    try:
        resultado = executar(carregar_args(argv))
    except Falha as f:
        # Falha também sai em JSON, com arquivo_gravado explícito: silêncio ou
        # stack trace solta deixariam o chamador supondo sucesso.
        print(json.dumps({
            "ok": False,
            "arquivo_gravado": False,
            "destino": None,
            "dois_gravados": 0,
            "erro": {"tipo": f.tipo, "detalhe": f.detalhe},
            "limites_declarados": LIMITES,
        }, ensure_ascii=False, indent=2))
        return f.codigo
    except KeyboardInterrupt:
        print(json.dumps({"ok": False, "arquivo_gravado": False, "destino": None,
                          "dois_gravados": 0,
                          "erro": {"tipo": "interrompido",
                                   "detalhe": "cancelado pelo operador"},
                          "limites_declarados": LIMITES},
                         ensure_ascii=False, indent=2))
        return 130
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
