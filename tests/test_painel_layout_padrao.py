"""A camada de padronização visual não pode regredir nem quebrar um tema.

Regras que valem para os DOIS temas: nenhuma cor literal na camada nova (só
variáveis), alvo de toque de 44px, foco visível e composer em grade.
"""
from __future__ import annotations

import re

from nomos.interface import painel_web as pw

CSS = pw._CSS
CAMADA = CSS.split("CAMADA DE PADRONIZAÇÃO")[1]


def test_camada_existe_e_vem_por_ultimo():
    assert "CAMADA DE PADRONIZAÇÃO" in CSS
    # por último => vence a cascata sem reescrever as regras antigas.
    # Compara com a regra ORIGINAL do .card (a camada nova também tem uma).
    assert CSS.index("CAMADA DE PADRONIZAÇÃO") > CSS.index(".card{background:")


def _sem_comentarios(css: str) -> str:
    """Tira /* … */ — os comentários CITAM as cores antigas ao explicar o bug
    corrigido, e citação não pinta nada na tela."""
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def test_nenhuma_cor_literal_na_camada_nova():
    """Cor literal quebraria um dos dois temas. Só var(--…) é aceito."""
    literais = re.findall(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(",
                          _sem_comentarios(CAMADA))
    assert literais == [], f"cor literal na camada padronizada: {literais}"


def test_alvo_de_toque_44px():
    assert "--alvo:44px" in CAMADA
    assert "min-height:var(--alvo)" in CAMADA


def test_foco_visivel_unico():
    assert ":focus-visible" in CAMADA
    assert "outline:var(--foco) solid var(--neon)" in CAMADA


def test_composer_em_grade_com_areas():
    assert "grid-template-areas" in CAMADA
    for area in ("controles", "texto", "enviar"):
        assert area in CAMADA


def test_responsivo_e_movimento_reduzido():
    assert "max-width:640px" in CAMADA
    assert "prefers-reduced-motion" in CAMADA
    assert "pointer:coarse" in CAMADA


def test_os_dois_temas_definem_as_mesmas_variaveis():
    """Se o claro esquecer uma variável que o escuro tem, ele quebra."""
    def vars_de(bloco: str) -> set[str]:
        return set(re.findall(r"(--[a-z0-9-]+):", bloco))
    escuro = CSS.split(":root{")[1].split("}")[0]
    claro = CSS.split(':root[data-tema="claro"]{')[1].split("}")[0]
    faltando = vars_de(escuro) - vars_de(claro)
    assert faltando == set(), f"tema claro não define: {faltando}"


# --------------------------------------------------------------------------
# Dois defeitos MEDIDOS no navegador, com teste que os prende
# --------------------------------------------------------------------------
def test_barra_do_topo_nao_tem_cor_literal_de_tema():
    """Medido: no tema claro a barra ficava rgba(10,15,13,.94) — escura sobre
    página clara, texto ilegível. A cor tem de derivar de --bg."""
    assert "color-mix(in srgb, var(--bg)" in CAMADA
    # e a regra derivada vem DEPOIS da literal antiga, para vencer a cascata
    assert CSS.index("color-mix(in srgb, var(--bg)") > CSS.index("rgba(10,15,13,.94)")


def test_scroll_margin_cobre_o_cabecalho_sticky():
    """Medido: cabeçalho 124px vs scroll-margin-top 5.5rem (88px) => o título
    parava 36px por baixo da barra ao clicar uma aba."""
    assert "--topo-h:8.5rem" in CAMADA          # piso > 124px se o JS não rodar
    assert "scroll-margin-top:calc(var(--topo-h)" in CAMADA
    piso_px = 8.5 * 16
    assert piso_px > 124, "o piso precisa cobrir o cabeçalho medido"


def test_js_publica_altura_real_do_cabecalho():
    """A barra quebra em tela estreita e fica mais alta — o piso fixo não
    bastaria. O JS mede e republica em --topo-h."""
    js = pw._JS
    assert "--topo-h" in js
    assert "ResizeObserver" in js
    assert "getBoundingClientRect().height" in js


def test_tema_claro_do_sistema_tambem_define_as_variaveis():
    """Terceiro caminho de tema (prefers-color-scheme) costuma ser esquecido."""
    bloco = CSS.split("prefers-color-scheme:light")[1].split("}}")[0]
    for v in ("--bg", "--surface", "--txt", "--neon", "--line"):
        assert v in bloco, f"tema claro do sistema não define {v}"
