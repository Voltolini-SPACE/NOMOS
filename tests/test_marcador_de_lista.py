"""`lstrip` com string multi-caractere remove CARACTERES, não prefixo.

A classe é traiçoeira porque funciona na maioria dos casos. Trazida pela
sessão 7f20d955, que levou dois bugs assim (`.lstrip("r/")` fazia "rust"
virar "ust"). Varri o `src/` e o caso que MORDE é este: em
`extrair_pontos`, `lstrip("#-*• ")` comia o sinal de número negativo.
"""
from __future__ import annotations

import pytest

from nomos.cognition.arquivos import _sem_marcador, extrair_pontos


@pytest.mark.parametrize("entrada,esperado", [
    ("- item", "item"),
    ("• ponto", "ponto"),
    ("* destaque", "destaque"),
    ("# Titulo", "Titulo"),
])
def test_marcador_simples_sai(entrada, esperado):
    assert _sem_marcador(entrada) == esperado


def test_nao_come_o_sinal_de_negativo():
    """O defeito medido: `"- -5 graus"` virava `"5 graus"` — sinal INVERTIDO.

    Numa transcrição de áudio ou num resumo de PDF isso troca o sentido em
    silêncio, e a saída continua plausível. É o pior tipo de erro.
    """
    assert _sem_marcador("- -5 graus") == "-5 graus"
    assert "- -12 C".lstrip("#-*• ") == "12 C"      # controle: o comportamento antigo


def test_nao_desemparelha_a_enfase():
    assert _sem_marcador("* *destaque*") == "*destaque*"


def test_nivel_de_titulo_repete_por_desenho():
    """`###` é nível, não conteúdo — aqui tirar todos os `#` é o certo."""
    assert _sem_marcador("### Terceiro nivel") == "Terceiro nivel"
    assert _sem_marcador("## Segundo") == "Segundo"


def test_segundo_marcador_de_lista_e_conteudo():
    """Diferente do título: um segundo `-` pode ser texto do próprio item."""
    assert _sem_marcador("-- item") == "- item"


def test_ponta_a_ponta_no_extrair_pontos():
    texto = "- -5 graus na madrugada de sabado\n- temperatura sobe no domingo\n"
    pontos = extrair_pontos(texto)
    assert pontos[0].startswith("-5"), pontos
