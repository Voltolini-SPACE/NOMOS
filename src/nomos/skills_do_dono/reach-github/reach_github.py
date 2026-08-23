"""Skill oficial reach-github — busca repositórios (e tenta código) no GitHub.

Postura desta skill em uma frase: ela NÃO toca em credencial nenhuma.

O manifesto declara A3_CRED_USE e um requisito `gh_token_host`, mas este código
roda ANÔNIMO de propósito. Ler `~/.config/gh/hosts.yml` (ou `GH_TOKEN` /
`GITHUB_TOKEN` do ambiente) arrastaria para dentro de uma execução governada um
segredo que o cofre do NOMOS não guarda e o gate A3 não consegue auditar — o
uso ficaria invisível justamente na camada que existe para torná-lo visível.
Preferimos entregar MENOS e dizer em alto e bom som o que faltou.

Prova disso no próprio código: o módulo `os` não é importado. Sem ele não há
`os.environ`, então "não li variável de ambiente" é verificável por inspeção,
não é promessa. O único toque em disco é `shutil.which("gh")`, que percorre o
PATH e não abre arquivo algum.

Consequência assumida: `/search/code` da API do GitHub EXIGE autenticação. Sem
token essa busca não acontece — e a skill devolve rc != 0 dizendo exatamente
isso, em vez de devolver lista vazia fingindo que procurou.

Entrada:  python3 reach_github.py <args.json>   |   ... < args.json (stdin)
Saída:    uma linha JSON no stdout. rc 0 = busca concluída.
"""
from __future__ import annotations

import json
import shutil
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"
# A API do GitHub responde 403 a requisição sem User-Agent. Identificar-se aqui
# é requisito do serviço, não telemetria: nenhum dado local vai no cabeçalho.
UA = "nomos-reach-github/1.0 (urllib da stdlib; anonimo)"
# O executor governado mata a skill em ~30 s. Estourar o tempo lá em cima faz o
# processo morrer SEM imprimir JSON — o pior desfecho possível, porque some a
# explicação. 15 s deixa folga para serializar e imprimir a falha honesta.
TIMEOUT_S = 15
LIMITE_PADRAO = 10
LIMITE_MAX = 50

TIPOS = {"repositorios": "/search/repositories", "codigo": "/search/code"}
ORDENACOES_REPO = {"estrelas": "stars", "forks": "forks", "atualizado": "updated"}

# Códigos de saída distintos de propósito, para quem chama poder ramificar sem
# precisar parsear texto de erro.
RC_OK = 0
RC_ENTRADA = 1        # pedido malformado (culpa do chamador)
RC_REDE = 2           # sem rota, DNS, TLS ou timeout (culpa do ambiente)
RC_CREDENCIAL = 3     # 401/403/429 — precisa de token ou estourou o limite
RC_RESPOSTA = 4       # o GitHub respondeu algo que não sabemos interpretar

CREDENCIAL_GH = (
    "Se um dia esta skill passar a usar o gh CLI, a credencial virá de "
    "~/.config/gh/hosts.yml — que fica FORA do cofre do NOMOS. O gate "
    "A3_CRED_USE não governa esse arquivo: ele autoriza a skill a usar "
    "credencial, mas não consegue mediar, revogar nem auditar um token que o "
    "gh guarda por conta própria no home do usuário."
)


def _ambiente() -> dict:
    """O que existe nesta máquina, sem abrir segredo nenhum.

    `shutil.which` só varre o PATH. Reportar a presença do `gh` importa porque
    o manifesto o declara obrigatório: quem lê a saída precisa saber que o
    resultado NÃO veio dele, mesmo quando ele está instalado.
    """
    return {
        "gh_no_path": shutil.which("gh") is not None,
        "usou_gh": False,
        "autenticado": False,
        "credencial_lida": "nenhuma",
        "nota_credencial": CREDENCIAL_GH,
    }


def _montar_consulta(args: dict) -> tuple[str, dict, str | None]:
    """Devolve (tipo, parametros, erro). Erro != None encerra antes da rede."""
    consulta = str(args.get("consulta") or args.get("q") or "").strip()
    if not consulta:
        return "", {}, "informe 'consulta' (o texto a procurar no GitHub)"

    tipo = str(args.get("tipo") or "repositorios").strip().lower()
    if tipo not in TIPOS:
        return "", {}, f"tipo inválido: {tipo!r} (use {' ou '.join(sorted(TIPOS))})"

    # Qualificadores viram parte do `q` porque é assim que a API do GitHub os
    # aceita — não existe parâmetro separado para linguagem ou estrelas.
    if args.get("linguagem"):
        consulta += f" language:{str(args['linguagem']).strip()}"
    if tipo == "repositorios" and args.get("min_estrelas") is not None:
        try:
            consulta += f" stars:>={int(args['min_estrelas'])}"
        except (TypeError, ValueError):
            return "", {}, "min_estrelas precisa ser número inteiro"

    try:
        limite = int(args.get("limite", LIMITE_PADRAO))
    except (TypeError, ValueError):
        return "", {}, "limite precisa ser número inteiro"
    limite = max(1, min(limite, LIMITE_MAX))

    params = {"q": consulta, "per_page": limite}
    ordenar = args.get("ordenar")
    if ordenar:
        if tipo != "repositorios":
            return "", {}, "'ordenar' só vale para tipo=repositorios"
        if ordenar not in ORDENACOES_REPO:
            return "", {}, (f"ordenar inválido: {ordenar!r} "
                            f"(use {' ou '.join(sorted(ORDENACOES_REPO))})")
        params["sort"] = ORDENACOES_REPO[ordenar]
        params["order"] = "desc"
    return tipo, params, None


def _resumir_repo(item: dict) -> dict:
    return {
        "nome": item.get("full_name"),
        "url": item.get("html_url"),
        "descricao": item.get("description"),
        "estrelas": item.get("stargazers_count"),
        "linguagem": item.get("language"),
        "atualizado_em": item.get("updated_at"),
        "arquivado": bool(item.get("archived")),
    }


def _resumir_codigo(item: dict) -> dict:
    return {
        "caminho": item.get("path"),
        "repositorio": (item.get("repository") or {}).get("full_name"),
        "url": item.get("html_url"),
    }


def _quota(cabecalhos) -> dict:
    """Estado do limite de taxa, tal como o GitHub o declarou NESTA resposta."""
    pegar = getattr(cabecalhos, "get", lambda _k: None)
    return {
        "restantes": pegar("X-RateLimit-Remaining"),
        "limite": pegar("X-RateLimit-Limit"),
        "reinicia_em_epoch": pegar("X-RateLimit-Reset"),
        "tentar_de_novo_em_s": pegar("Retry-After"),
    }


def executar(args: dict) -> tuple[dict, int]:
    base = {"skill": "reach-github", **_ambiente()}
    tipo, params, erro = _montar_consulta(args)
    if erro:
        return {**base, "ok": False, "erro": erro,
                "exemplo": {"consulta": "sqlite fts5", "tipo": "repositorios",
                            "limite": 5, "ordenar": "estrelas"}}, RC_ENTRADA

    url = f"{API}{TIPOS[tipo]}?{urllib.parse.urlencode(params)}"
    base.update({"tipo": tipo, "consulta": params["q"], "endpoint": url})
    if tipo == "codigo":
        base["aviso"] = ("/search/code do GitHub EXIGE autenticação; anônimo "
                         "isto volta 401/403 — e a skill vai dizer, não fingir.")

    pedido = urllib.request.Request(
        url, headers={"User-Agent": UA,
                      "Accept": "application/vnd.github+json",
                      "X-GitHub-Api-Version": "2022-11-28"})
    try:
        # Contexto TLS padrão: verificação de certificado LIGADA. Desligá-la
        # trocaria uma falha visível de ambiente por silêncio inseguro.
        with urllib.request.urlopen(pedido, timeout=TIMEOUT_S,
                                    context=ssl.create_default_context()) as resp:
            corpo = resp.read().decode("utf-8", errors="replace")
            quota = _quota(resp.headers)
    except urllib.error.HTTPError as exc:
        # HTTPError é subclasse de URLError: este ramo precisa vir ANTES, senão
        # o tratamento de rede engole o 403 e o diagnóstico sai errado.
        quota = _quota(exc.headers)
        detalhe = ""
        try:
            corpo_erro = exc.read().decode("utf-8", errors="replace")
            detalhe = json.loads(corpo_erro).get("message", "")
        except Exception:
            pass   # corpo de erro ilegível não muda o diagnóstico: o status basta
        if exc.code in (401, 403, 429):
            esgotou = str(quota.get("restantes")) == "0"
            return {**base, "ok": False, "http_status": exc.code,
                    "limite_de_taxa": esgotou,
                    "precisa_credencial": not esgotou,
                    "quota": quota,
                    "erro": ("limite de taxa da API pública esgotado" if esgotou
                             else f"o GitHub recusou a chamada anônima ({exc.code})"),
                    "detalhe_github": detalhe,
                    "o_que_falta": ("esperar o reinício do limite" if esgotou else
                                    "um token — que esta skill se recusa a ler, "
                                    "por vir de fora do cofre")}, RC_CREDENCIAL
        return {**base, "ok": False, "http_status": exc.code, "quota": quota,
                "erro": f"HTTP {exc.code} inesperado",
                "detalhe_github": detalhe}, RC_RESPOSTA
    except urllib.error.URLError as exc:
        # urllib embrulha a falha real em `reason`; um erro de certificado chega
        # aqui como URLError(SSLCertVerificationError) e NÃO no `except ssl`.
        motivo = getattr(exc, "reason", exc)
        return {**base, "ok": False, "rede_ok": False,
                "erro": "não consegui alcançar api.github.com",
                "falha_tls": isinstance(motivo, ssl.SSLError),
                "detalhe": f"{type(motivo).__name__}: {motivo}",
                "nota": "sem rede não há resultado; devolver lista vazia aqui "
                        "seria mentir por omissão"}, RC_REDE
    except (socket.timeout, TimeoutError, ssl.SSLError, OSError) as exc:
        return {**base, "ok": False, "rede_ok": False,
                "erro": "falha de rede antes de qualquer resposta",
                "falha_tls": isinstance(exc, ssl.SSLError),
                "detalhe": f"{type(exc).__name__}: {exc}",
                "nota": "certificado NUNCA é ignorado — a skill prefere falhar"}, RC_REDE

    try:
        dados = json.loads(corpo)
    except ValueError:
        return {**base, "ok": False, "quota": quota,
                "erro": "a resposta não era JSON válido",
                "amostra": corpo[:200]}, RC_RESPOSTA

    itens = dados.get("items")
    if not isinstance(itens, list):
        return {**base, "ok": False, "quota": quota,
                "erro": "resposta sem lista 'items'",
                "chaves_recebidas": sorted(dados)[:10]}, RC_RESPOSTA

    resumir = _resumir_repo if tipo == "repositorios" else _resumir_codigo
    return {**base, "ok": True, "rede_ok": True,
            "total_no_github": dados.get("total_count"),
            "resultados_devolvidos": len(itens),
            "incompleto_por_timeout_do_github": bool(dados.get("incomplete_results")),
            "resultados": [resumir(i) for i in itens if isinstance(i, dict)],
            "quota": quota,
            "limites_desta_skill": [
                "roda anônima: a API pública dá ~10 buscas/minuto por IP",
                "busca de código exige token e por isso falha aqui",
                "não lê ~/.config/gh nem variável de ambiente com token",
            ]}, RC_OK


def _ler_argumentos(argv: list[str]) -> tuple[dict, str | None]:
    """args.json por caminho, ou stdin (JSON ou texto cru = a própria consulta).

    Não inventamos consulta padrão: uma busca default devolveria resultado de
    verdade para um pedido que ninguém fez, e isso engana mais do que recusar.
    """
    if len(argv) > 1:
        try:
            with open(argv[1], encoding="utf-8") as fh:
                dados = json.load(fh)
        except OSError as exc:
            return {}, f"não consegui ler o arquivo de argumentos: {exc}"
        except ValueError as exc:
            return {}, f"arquivo de argumentos não é JSON válido: {exc}"
        if not isinstance(dados, dict):
            return {}, "o arquivo de argumentos precisa ser um objeto JSON"
        return dados, None
    if sys.stdin.isatty():
        return {}, None   # sem args e sem pipe: cai no erro de entrada, com exemplo
    bruto = sys.stdin.read().strip()
    if not bruto:
        return {}, None
    try:
        dados = json.loads(bruto)
    except ValueError:
        return {"consulta": bruto}, None   # texto solto no pipe é a consulta
    if not isinstance(dados, dict):
        return {"consulta": bruto}, None
    return dados, None


if __name__ == "__main__":
    args, falha = _ler_argumentos(sys.argv)
    if falha:
        print(json.dumps({"skill": "reach-github", "ok": False, "erro": falha},
                         ensure_ascii=False))
        sys.exit(RC_ENTRADA)
    saida, rc = executar(args)
    print(json.dumps(saida, ensure_ascii=False))
    sys.exit(rc)
