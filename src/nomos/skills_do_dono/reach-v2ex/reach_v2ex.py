#!/usr/bin/env python3
"""reach-v2ex — tópicos quentes do V2EX pela API pública, sem login.

O que esta skill faz
--------------------
Uma chamada GET a um endpoint FIXO do V2EX (`hot.json` ou `latest.json`) e
devolve, de cada tópico, **título, link e contagem de respostas**. Nada mais
sai da máquina: sem cookie, sem chave, sem cabeçalho de identificação além do
User-Agent.

Fronteiras declaradas (o que ela NÃO faz)
-----------------------------------------
* não faz login, não lê tópico privado, não posta, não vota;
* não aceita URL arbitrária — o endereço vem de uma lista fechada aqui dentro.
  É de propósito: uma skill de rede que aceita URL do chamador vira ponte de
  SSRF para dentro da rede local. Quem quiser ler página qualquer usa a skill
  `reach-readpage`, que declara esse risco no próprio manifesto;
* não segue redirecionamento (`curl` sem `-L`, urllib com redirect barrado):
  um 302 poderia levar a chamada para host que ninguém aprovou;
* não guarda cache nem histórico — cada execução fala com a origem.

Permissões do manifesto (skill.json): A1_WRITE_LOCAL e A2_NET_EGRESS. O código
abaixo só faz egresso de rede e escreve em stdout; nenhum arquivo é criado, o
que fica DENTRO do que A1 permite (permissão é teto, não obrigação).

Transporte: por que dois caminhos
---------------------------------
O manifesto declara `curl` como binário OBRIGATÓRIO, e a especificação desta
skill pede `urllib` da biblioteca padrão. Não é contradição: `urllib` é o
caminho preferido (zero processo filho) e `curl` é a rede de segurança medida.
Dentro da cerca seatbelt do NOMOS (`runtime/sandbox.py`) o interpretador só
enxerga o próprio prefixo; se o armazém de CAs do Python estiver fora dele, o
handshake TLS morre com erro de certificado. O `curl` do sistema usa o
SecureTransport do macOS e continua funcionando — foi o que se mediu.

Em NENHUM caso a verificação de certificado é desligada. Preferir cair para
`curl` a aceitar TLS sem verificação é escolha deliberada: um fallback que
"funciona sempre" mentindo sobre a autenticidade do servidor é pior que falhar.
Cada tentativa e cada motivo de falha vão para o campo `tentativas` da saída.

Entrada
-------
    python3 reach_v2ex.py <caminho-para-args.json>

Sem argumento, lê JSON do stdin (só se houver dado pronto — ver `_ler_stdin`);
sem nada disso, usa os padrões. Parâmetros aceitos:

    fonte             "quentes" (padrão) | "recentes"   (aliases: hot | latest)
    limite            int 1..50, padrão 10
    minimo_respostas  int >= 0, padrão 0 — filtra por contagem de respostas
    timeout           int 1..120 segundos, padrão 20
    transporte        "auto" (padrão) | "urllib"

Saída
-----
JSON único em stdout, sempre — inclusive na falha. Códigos de saída:

    0  sucesso
    2  parâmetro/entrada inválida (nada foi para a rede)
    3  falha de transporte: rede, TLS, HTTP != 200, curl ausente
    4  resposta chegou mas não é o JSON que o V2EX documenta
"""
from __future__ import annotations

import json
import os
import select
import shutil
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

NOME = "reach-v2ex"
VERSAO = "1.0.0"

# Lista fechada de endereços. A chave é o que o chamador escolhe; a URL nunca
# vem de fora. Trocar isto por um parâmetro `url` reabriria o SSRF descrito no
# cabeçalho.
FONTES = {
    "quentes": "https://www.v2ex.com/api/topics/hot.json",
    "recentes": "https://www.v2ex.com/api/topics/latest.json",
}
ALIASES = {"hot": "quentes", "quente": "quentes", "latest": "recentes",
           "recente": "recentes", "novos": "recentes"}

# O V2EX responde a cliente anônimo, mas rejeita User-Agent vazio/robotizado em
# parte das rotas. Identificar-se honestamente (nome da skill) é melhor que
# fingir ser um navegador: se um dia o V2EX quiser bloquear, que bloqueie o que
# realmente somos.
UA = f"nomos-{NOME}/{VERSAO} (+stdlib urllib; sem login)"
CABECALHOS = {"User-Agent": UA, "Accept": "application/json"}

LIMITE_CORPO = 8 * 1024 * 1024
"""Teto de leitura do corpo. Sem teto, um servidor (ou um intermediário) pode
empurrar bytes até estourar a memória do processo; o `latest.json` real mede
~280 KB, então 8 MB é folga de mais de uma ordem de grandeza."""


class ErroDeUso(Exception):
    """Entrada inválida: recusa ANTES de tocar a rede (código de saída 2)."""


class ErroDeTransporte(Exception):
    """Nenhum transporte conseguiu buscar o recurso (código de saída 3).

    Carrega `tentativas` porque o diagnóstico ("urllib morreu no certificado E
    curl não existe") é a parte útil da falha; sem ele a saída diria só
    "sem rede", que é diagnóstico de nada.
    """

    def __init__(self, mensagem: str, tentativas: list[dict] | None = None):
        super().__init__(mensagem)
        self.tentativas = tentativas or []


# --------------------------------------------------------------- entrada

def _ler_stdin() -> str:
    """Lê stdin só se já houver dado disponível.

    Ler stdin às cegas trava o processo até o timeout do sandbox quando o pai
    deixa um cano aberto sem escrever nada — falha que se manifesta como
    "a skill é lenta", não como erro. O `select` com 0,25 s transforma isso em
    'não havia entrada', que é a verdade.
    """
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return ""
        pronto, _, _ = select.select([sys.stdin], [], [], 0.25)
        return sys.stdin.read() if pronto else ""
    except Exception:
        return ""   # stdin fechado/indisponível não é erro: é ausência de entrada


def carregar_parametros(argv: list[str]) -> dict:
    if len(argv) > 1 and argv[1] not in ("-", ""):
        caminho = argv[1]
        if not os.path.isfile(caminho):
            raise ErroDeUso(f"arquivo de argumentos nao encontrado: {caminho}")
        try:
            bruto = open(caminho, "rb").read().decode("utf-8")
        except OSError as e:
            raise ErroDeUso(f"nao foi possivel ler {caminho}: {e}") from e
    else:
        bruto = _ler_stdin()

    if not bruto.strip():
        return {}
    try:
        dados = json.loads(bruto)
    except json.JSONDecodeError as e:
        raise ErroDeUso(f"JSON de argumentos invalido: {e}") from e
    if isinstance(dados, dict) and isinstance(dados.get("args"), dict):
        # Alguns chamadores embrulham os parâmetros em {"args": {...}}.
        dados = dados["args"]
    if not isinstance(dados, dict):
        raise ErroDeUso("JSON de argumentos deve ser um objeto")
    return dados


def _inteiro(params: dict, chave: str, padrao: int, minimo: int, maximo: int) -> int:
    valor = params.get(chave, padrao)
    if isinstance(valor, bool) or not isinstance(valor, (int, float, str)):
        raise ErroDeUso(f"{chave} deve ser inteiro entre {minimo} e {maximo}")
    try:
        n = int(valor)
    except (TypeError, ValueError) as e:
        raise ErroDeUso(f"{chave} deve ser inteiro entre {minimo} e {maximo}") from e
    if n < minimo or n > maximo:
        raise ErroDeUso(f"{chave}={n} fora da faixa {minimo}..{maximo}")
    return n


def normalizar(params: dict) -> dict:
    fonte_bruta = params.get("fonte", "quentes")
    if not isinstance(fonte_bruta, str):
        raise ErroDeUso("fonte deve ser texto")
    # Comparação literal depois de normalizar caixa: nada de casar por prefixo
    # ou por padrão — "hotdog" não pode virar "hot".
    fonte = ALIASES.get(fonte_bruta.strip().lower(), fonte_bruta.strip().lower())
    if fonte not in FONTES:
        raise ErroDeUso(
            f"fonte desconhecida: {fonte_bruta!r} "
            f"(use {' ou '.join(sorted(FONTES))})")

    transporte = params.get("transporte", "auto")
    if not isinstance(transporte, str) or \
            transporte.strip().lower() not in ("auto", "urllib"):
        raise ErroDeUso(
            f"transporte desconhecido: {transporte!r} (use auto, urllib ou curl)")

    return {
        "fonte": fonte,
        "url": FONTES[fonte],
        "limite": _inteiro(params, "limite", 10, 1, 50),
        "minimo_respostas": _inteiro(params, "minimo_respostas", 0, 0, 1_000_000),
        "timeout": _inteiro(params, "timeout", 20, 1, 120),
        "transporte": transporte.strip().lower(),
    }


# --------------------------------------------------------------- transporte

class _SemRedirect(urllib.request.HTTPRedirectHandler):
    """Barra redirecionamento: o destino aprovado é o da lista FONTES, e um
    301/302 escolhido pelo servidor levaria a chamada para outro host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(
            req.full_url, code, f"redirecionamento recusado para {newurl}", headers, fp)


def buscar_urllib(url: str, timeout: int) -> bytes:
    req = urllib.request.Request(url, headers=CABECALHOS, method="GET")
    abridor = urllib.request.build_opener(_SemRedirect)
    # nosec B310 - url vem de FONTES (constante), nunca do chamador
    with abridor.open(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise ErroDeTransporte(f"HTTP {resp.status} em {url}")
        return resp.read(LIMITE_CORPO + 1)


def buscar(cfg: dict) -> tuple[bytes, str, list[dict]]:
    """Devolve (corpo, transporte_usado, tentativas). Cada tentativa registra o
    motivo da falha — silêncio aqui esconderia POR QUE o caminho preferido caiu."""
    # Transporte UNICO: urllib. O fallback por `curl` foi removido em 23/08 —
    # era `subprocess.run`, ou seja execucao de processo, e o manifesto declara
    # apenas A1_WRITE_LOCAL + A2_NET_EGRESS. O contrato do registro e explicito:
    # permissao nao declarada nao executa. As saidas eram declarar
    # A5_CODE_EXEC por um fallback dispensavel, ou tirar o fallback. Medido
    # nesta maquina: urllib puro devolve HTTP 200 e os 10 topicos, entao o curl
    # nao era necessario — inflar permissao por conveniencia seria o pior dos
    # dois. Falha de TLS agora e reportada (rc=3), nao contornada por processo.
    ordem = ["urllib"] if cfg["transporte"] in ("auto", "urllib") else [cfg["transporte"]]

    tentativas: list[dict] = []
    for nome in ordem:
        try:
            corpo = buscar_urllib(
                cfg["url"], cfg["timeout"])
            if len(corpo) > LIMITE_CORPO:
                raise ErroDeTransporte(f"corpo acima de {LIMITE_CORPO} bytes")
            tentativas.append({"transporte": nome, "ok": True, "erro": None})
            return corpo, nome, tentativas
        except Exception as e:
            tentativas.append({"transporte": nome, "ok": False,
                               "erro": f"{type(e).__name__}: {e}"})
    raise ErroDeTransporte("nenhum transporte funcionou", tentativas)


# --------------------------------------------------------------- extração

def _iso(epoch) -> str | None:
    """Epoch do V2EX -> ISO 8601 UTC. Devolve None em vez de inventar data."""
    if not isinstance(epoch, (int, float)) or isinstance(epoch, bool):
        return None
    try:
        return datetime.fromtimestamp(float(epoch), timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def extrair(corpo: bytes, cfg: dict) -> tuple[list[dict], int, list[str]]:
    limitacoes: list[str] = []
    try:
        dados = json.loads(corpo.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"resposta nao e JSON UTF-8 valido: {e}") from e
    if not isinstance(dados, list):
        raise ValueError(
            f"esperava lista de topicos, veio {type(dados).__name__}")

    total = len(dados)
    sem_respostas = 0
    topicos: list[dict] = []
    for item in dados:
        if not isinstance(item, dict):
            continue
        titulo = item.get("title")
        link = item.get("url")
        respostas = item.get("replies")
        if isinstance(respostas, bool) or not isinstance(respostas, int):
            # Sem contagem confiável o tópico não pode passar por um filtro de
            # contagem: barrar é fail-closed, deixar passar seria fabricar.
            respostas = None
            sem_respostas += 1
        if cfg["minimo_respostas"] > 0 and (
                respostas is None or respostas < cfg["minimo_respostas"]):
            continue
        no = item.get("node")
        topicos.append({
            "titulo": titulo if isinstance(titulo, str) else None,
            "link": link if isinstance(link, str) else None,
            "respostas": respostas,
            "no": (no or {}).get("name") if isinstance(no, dict) else None,
            "id": item.get("id") if isinstance(item.get("id"), int) else None,
            "criado_em": _iso(item.get("created")),
        })
        if len(topicos) >= cfg["limite"]:
            break

    if sem_respostas:
        limitacoes.append(
            f"{sem_respostas} topico(s) vieram sem campo 'replies' utilizavel; "
            "respostas=null" + (" e foram excluidos pelo filtro"
                                if cfg["minimo_respostas"] > 0 else ""))
    faltando = [t["id"] for t in topicos if not t["titulo"] or not t["link"]]
    if faltando:
        limitacoes.append(f"topico(s) sem titulo ou link na origem: {faltando}")
    return topicos, total, limitacoes


# --------------------------------------------------------------- saída

def emitir(payload: dict, codigo: int) -> int:
    """Escreve o JSON em bytes UTF-8.

    `print()` usaria a codificação do stdout, e título de V2EX é chinês: num
    ambiente com stdout ASCII isso morreria em UnicodeEncodeError DEPOIS de a
    rede já ter sido usada. Escrever bytes tira essa variável do caminho.
    """
    texto = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False)
    sys.stdout.buffer.write(texto.encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()
    return codigo


def falha(codigo_erro: str, mensagem: str, saida: int, **extra) -> int:
    payload = {
        "ok": False,
        "skill": NOME,
        "versao": VERSAO,
        "obtido_em": datetime.now(timezone.utc).isoformat(),
        "topicos": [],
        "total_recebido": 0,
        "total_devolvido": 0,
        "erro": {"codigo": codigo_erro, "mensagem": mensagem},
    }
    payload.update(extra)
    return emitir(payload, saida)


def main(argv: list[str]) -> int:
    try:
        cfg = normalizar(carregar_parametros(argv))
    except ErroDeUso as e:
        return falha("entrada_invalida", str(e), 2)

    try:
        corpo, transporte_usado, tentativas = buscar(cfg)
    except ErroDeTransporte as e:
        return falha("transporte_indisponivel", str(e), 3,
                     fonte=cfg["fonte"], endpoint=cfg["url"],
                     transporte_usado=None, tentativas=e.tentativas)
    except Exception as e:   # rede tem falha que nao herda de ErroDeTransporte
        return falha("transporte_indisponivel", f"{type(e).__name__}: {e}", 3,
                     fonte=cfg["fonte"], endpoint=cfg["url"],
                     transporte_usado=None, tentativas=[])

    try:
        topicos, total, limitacoes = extrair(corpo, cfg)
    except ValueError as e:
        return falha("resposta_inesperada", str(e), 4,
                     fonte=cfg["fonte"], endpoint=cfg["url"],
                     transporte_usado=transporte_usado, tentativas=tentativas)

    if transporte_usado != "urllib" and cfg["transporte"] == "auto":
        limitacoes.append(
            "urllib falhou e a busca foi feita por curl — ver 'tentativas'")

    return emitir({
        "ok": True,
        "skill": NOME,
        "versao": VERSAO,
        "fonte": cfg["fonte"],
        "endpoint": cfg["url"],
        "obtido_em": datetime.now(timezone.utc).isoformat(),
        "transporte_usado": transporte_usado,
        "tentativas": tentativas,
        "autenticado": False,
        "filtro": {"limite": cfg["limite"],
                   "minimo_respostas": cfg["minimo_respostas"]},
        "total_recebido": total,
        "total_devolvido": len(topicos),
        "topicos": topicos,
        "limitacoes": limitacoes,
        "erro": None,
    }, 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
