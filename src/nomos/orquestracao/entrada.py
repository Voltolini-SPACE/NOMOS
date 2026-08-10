"""NOMOS orquestracao.entrada — o plano é entrada hostil (P3).

Duas classes de ambiguidade, com defesas DIFERENTES. Confundi-las produziria
uma sensação de cobertura que nenhuma das duas dá sozinha.

## 1. Chaves duplicadas no JSON BRUTO

    {"alvo": "/ws/benigno.txt", "alvo": "/etc/passwd"}

`json.loads` aceita isso e devolve `{"alvo": "/etc/passwd"}` — a última vence,
em silêncio. Depois que o `dict` existe, a ambiguidade JÁ FOI RESOLVIDA e não
há como detectá-la: o campo tem um valor só. Um leitor humano revisando o
plano, um log que mostre o texto original, e o executor podem discordar sobre
qual valor é o real.

A defesa só funciona ANTES da materialização — daí `object_pairs_hook`, que
recebe os pares na ordem em que apareceram, inclusive em objetos ANINHADOS.

## 2. Aliases semânticos de autoridade

    {"alvo": "/ws/benigno.txt", "target": "/etc/passwd"}

Aqui não há duplicata nenhuma para o JSON: são duas chaves distintas. O
problema é semântico — duas representações da MESMA autoridade. Normalizar
escolhendo uma faz o sistema decidir por conta própria qual das duas o autor
quis, e a resposta errada é indistinguível da certa.

Recusa nos dois casos, nunca escolha. Um plano ambíguo é um plano que o autor
precisa reescrever.
"""
from __future__ import annotations

import json


class ErroEntrada(ValueError):
    """Plano ambíguo, malformado ou com autoridade duplicada."""


# Campos que carregam AUTORIDADE e têm mais de uma grafia plausível. Cada
# grupo é um conjunto de sinônimos: dois membros do mesmo grupo no mesmo
# objeto é ambiguidade, não conveniência.
GRUPOS_DE_ALIAS: tuple[frozenset[str], ...] = (
    frozenset({"alvo", "target"}),
    frozenset({"_sujeito", "sujeito", "subject"}),
    frozenset({"cwd", "raiz", "root"}),
    frozenset({"capacidade", "capability", "capability_id", "ferramenta"}),
    frozenset({"executor", "backend"}),
    frozenset({"risco", "risk_class", "classe_de_risco"}),
    frozenset({"politica", "policy", "policy_version"}),
    frozenset({"aprovacao", "approval_id"}),
    frozenset({"escopo_dados", "data_scope"}),
    frozenset({"escopo_controle", "control_scope"}),
    frozenset({"timeout", "timeout_s", "prazo"}),
    frozenset({"retry", "tentativas", "retries"}),
)


def _pares_sem_duplicata(pares):
    """`object_pairs_hook`: recusa chave repetida em QUALQUER nível.

    Roda durante a desserialização, com os pares na ordem original — é o único
    momento em que a duplicata ainda é visível.
    """
    vistas = set()
    repetidas = []
    for chave, _valor in pares:
        if chave in vistas:
            repetidas.append(chave)
        vistas.add(chave)
    if repetidas:
        raise ErroEntrada(
            f"chave(s) duplicada(s) no JSON: {sorted(set(repetidas))} — o "
            "plano é ambíguo e não será interpretado. `json.loads` deixaria a "
            "última vencer em silêncio, e quem lê o plano veria outro valor")
    return dict(pares)


def _recusar_aliases(obj, caminho: str = "$") -> None:
    """Recusa dois sinônimos de autoridade no MESMO objeto, recursivamente."""
    if isinstance(obj, dict):
        presentes = set(obj)
        for grupo in GRUPOS_DE_ALIAS:
            colisao = sorted(presentes & grupo)
            if len(colisao) > 1:
                raise ErroEntrada(
                    f"autoridade ambígua em {caminho}: {colisao} representam a "
                    "mesma coisa. Escolha UMA — o NOMOS não decide por você "
                    "qual delas você quis dizer")
        for chave, valor in obj.items():
            _recusar_aliases(valor, f"{caminho}.{chave}")
    elif isinstance(obj, (list, tuple)):
        for i, item in enumerate(obj):
            _recusar_aliases(item, f"{caminho}[{i}]")


def carregar_plano(texto: str):
    """JSON de plano → estrutura, ou `ErroEntrada`.

    É o ÚNICO ponto por onde texto de plano deve entrar. Fazer
    `json.loads` direto em outro lugar reabre a duplicata silenciosa.
    """
    if not isinstance(texto, str):
        raise ErroEntrada("plano precisa ser texto JSON")
    try:
        dados = json.loads(texto, object_pairs_hook=_pares_sem_duplicata)
    except ErroEntrada:
        raise
    except json.JSONDecodeError as exc:
        raise ErroEntrada(f"JSON inválido: {exc}") from None
    _recusar_aliases(dados)
    return dados


def validar_params(params, caminho: str = "$") -> None:
    """Mesma checagem de alias para params já materializados.

    Existe porque nem todo plano chega como texto: a API in-process recebe
    `dict`. Ali a duplicata bruta é impossível de detectar (o `dict` já existe),
    mas a ambiguidade SEMÂNTICA continua detectável — e é a que mais importa,
    porque é a que um autor de plano escreve sem perceber.
    """
    _recusar_aliases(params, caminho)
