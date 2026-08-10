"""NOMOS adapters.estrito — validação de argumentos vindos de PLANO.

O plano é entrada NÃO CONFIÁVEL. Ele foi escrito por um modelo, ou por alguém
que não é o dono da máquina, e chega como JSON. Tratá-lo com as regras de
verdade do Python — onde toda string não vazia é verdadeira — transforma um
engano de digitação em autoridade.

O defeito que originou este módulo, achado por censo adversarial:

    recursivo = bool(pedido.arg("recursivo", False))

    bool("nao")   is True
    bool("false") is True
    bool("0")     is True
    bool("[]")    is True

Um plano que escreveu `{"recursivo": "nao"}` querendo dizer **não** apagava a
árvore inteira — com efeito irreversível, sob uma aprovação rotulada "A1 ·
escrever arquivos locais". Não era um bug de digitação do plano: era o sistema
lendo "não" como "sim".

## A regra

Nenhum argumento de plano pode mudar semântica ou autoridade por coerção
implícita. Ou o valor está no contrato, ou é `VALIDATION_ERROR` — e
`VALIDATION_ERROR` acontece ANTES de qualquer efeito.

## Por que booleano NÃO aceita string

O contrato do plano é JSON, e JSON tem booleano de verdade (`true`/`false`).
Aceitar também `"true"`/`"false"` pareceria gentileza barata, mas abre a
pergunta seguinte — e `"yes"`? e `"1"`? e `"sim"`? — que não tem resposta
principiada. Um contrato que já expressa o valor nativamente não ganha nada
tolerando a versão textual, e perde a única linha nítida que existe. Quem
mandar string recebe um erro que diz exatamente o que mandar.

## Por que `bool` não é `int` aqui

Em Python, `isinstance(True, int)` é verdadeiro: `True` passaria por uma
validação de inteiro e viraria `1`. Um `{"limite": true}` lido como "1 linha"
é a mesma família de defeito, com outra roupa. Os validadores abaixo recusam
`bool` onde esperam número, de propósito.
"""
from __future__ import annotations

from nomos.adapters.contrato import ErroInvalido


def bool_estrito(valor, nome: str, *, padrao: bool = False) -> bool:
    """Booleano de verdade, ou erro. Nunca truthiness."""
    if valor is None:
        return padrao
    if valor is True or valor is False:
        return valor
    raise ErroInvalido(
        f"'{nome}' precisa ser booleano JSON (true/false), recebido "
        f"{type(valor).__name__} {valor!r} — o NOMOS não interpreta "
        f"texto nem número como booleano, porque 'nao' e '0' seriam "
        f"verdadeiros e o efeito seria o oposto do pedido")


def inteiro_estrito(valor, nome: str, *, padrao: int | None = None,
                    minimo: int | None = None, maximo: int | None = None,
                    obrigatorio: bool = False) -> int | None:
    """Inteiro de verdade, dentro da faixa declarada.

    `obrigatorio` é EXPLÍCITO. A primeira versão inferia obrigatoriedade de
    "tem mínimo declarado", o que fez `limite` ausente virar erro em cinco
    testes de leitura: ter piso quando presente não é a mesma coisa que ter de
    estar presente. Inferir contrato a partir de um campo vizinho é o mesmo
    vício que este módulo existe para eliminar, só que do lado do
    implementador.
    """
    if valor is None or valor == "":
        if obrigatorio:
            raise ErroInvalido(f"'{nome}' é obrigatório")
        return padrao
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ErroInvalido(
            f"'{nome}' precisa ser inteiro JSON, recebido "
            f"{type(valor).__name__} {valor!r}")
    if minimo is not None and valor < minimo:
        raise ErroInvalido(f"'{nome}' precisa ser >= {minimo} (recebido {valor})")
    if maximo is not None and valor > maximo:
        raise ErroInvalido(f"'{nome}' precisa ser <= {maximo} (recebido {valor})")
    return valor


def numero_estrito(valor, nome: str, *, padrao: float | None = None,
                   minimo: float | None = None,
                   maximo: float | None = None) -> float | None:
    """Número (int ou float) de verdade, dentro da faixa declarada."""
    if valor is None or valor == "":
        return padrao
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ErroInvalido(
            f"'{nome}' precisa ser número JSON, recebido "
            f"{type(valor).__name__} {valor!r}")
    valor = float(valor)
    if valor != valor:                       # NaN não é comparável
        raise ErroInvalido(f"'{nome}' não pode ser NaN")
    if minimo is not None and valor < minimo:
        raise ErroInvalido(f"'{nome}' precisa ser >= {minimo} (recebido {valor})")
    if maximo is not None and valor > maximo:
        raise ErroInvalido(f"'{nome}' precisa ser <= {maximo} (recebido {valor})")
    return valor


def enum_estrito(valor, nome: str, opcoes, *, padrao=None):
    """Um dos valores do contrato, exatamente. Sem normalizar, sem adivinhar."""
    if valor is None:
        return padrao
    if valor not in opcoes:
        raise ErroInvalido(
            f"'{nome}' precisa ser um de {sorted(opcoes)}, recebido {valor!r}")
    return valor


def texto_estrito(valor, nome: str, *, obrigatorio: bool = True,
                  maximo: int = 4096) -> str:
    """Texto de verdade. `str(objeto)` viraria nome de arquivo plausível."""
    if valor is None or valor == "":
        if obrigatorio:
            raise ErroInvalido(f"'{nome}' é obrigatório")
        return ""
    if not isinstance(valor, str):
        raise ErroInvalido(
            f"'{nome}' precisa ser texto, recebido "
            f"{type(valor).__name__} {valor!r}")
    if len(valor) > maximo:
        raise ErroInvalido(f"'{nome}' excede {maximo} caracteres")
    if "\x00" in valor:
        raise ErroInvalido(f"'{nome}' contém byte NUL")
    return valor


def recusar_argumento(pedido, nome: str, sugestao: str) -> None:
    """Recusa um argumento que NÃO pertence a esta capacidade.

    Ignorar em silêncio seria pior que aceitar: o plano que manda
    `recursivo=true` para `fs-apagar` acredita ter apagado a árvore, e segue
    adiante sobre uma premissa falsa. Autoridade separada por capacidade só
    funciona se pedir a errada FALHAR.
    """
    if pedido.arg(nome, None) is not None:
        raise ErroInvalido(
            f"'{nome}' não é aceito por esta capacidade — {sugestao}")
