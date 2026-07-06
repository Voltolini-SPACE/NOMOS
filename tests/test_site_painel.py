"""Site — seção Painel: fotos reais, acessíveis e leves (MC34.2).

O marketing do NOMOS segue a lei da casa: nunca finge. As imagens da seção
#painel têm de EXISTIR no repositório (nada de hotlink), pesar pouco
(landing rápida), carregar preguiçoso (lazy) e descrever o que mostram
(alt) — e a seção precisa estar ligada na navegação e no hero.
"""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SITE = RAIZ / "site" / "index.html"
ASSETS = RAIZ / "site" / "assets"
PESO_MAX_KB = 300          # cada screenshot retina otimizado
PESO_MAX_TOTAL_KB = 700    # todas as imagens do painel somadas


def _html() -> str:
    return SITE.read_text(encoding="utf-8")


def _imgs_do_painel(html: str) -> list[str]:
    secao = html.split('id="painel"', 1)[1].split("<!-- Segurança", 1)[0]
    return re.findall(r'<img src="assets/(painel-[^"]+)"', secao)


# 1. seção existe, na nav e no hero
def test_secao_painel_ligada_na_navegacao_e_no_hero():
    html = _html()
    assert 'id="painel"' in html
    assert 'href="#painel"' in html.split("<main", 1)[0], "nav sem link p/ painel"
    hero = html.split('class="hero"', 1)[1].split("</section>", 1)[0]
    assert 'href="#painel"' in hero, "hero sem CTA para o painel"


# 2. toda imagem referenciada existe no repo (nada de link quebrado)
def test_imagens_do_painel_existem_no_repo():
    imgs = _imgs_do_painel(_html())
    assert len(imgs) >= 3, f"esperava >=3 screenshots, achei {imgs}"
    for nome in imgs:
        assert (ASSETS / nome).is_file(), f"imagem ausente: assets/{nome}"


# 3. leves de verdade — landing não pode pesar
def test_imagens_leves():
    imgs = _imgs_do_painel(_html())
    total = 0
    for nome in imgs:
        kb = (ASSETS / nome).stat().st_size // 1024
        total += kb
        assert kb <= PESO_MAX_KB, f"{nome}: {kb} KB > {PESO_MAX_KB} KB"
    assert total <= PESO_MAX_TOTAL_KB, f"total {total} KB > {PESO_MAX_TOTAL_KB} KB"


# 4. acessível e sem CLS: alt descritivo, lazy, dimensões declaradas
def test_imagens_acessiveis_lazy_e_com_dimensoes():
    html = _html()
    secao = html.split('id="painel"', 1)[1].split("<!-- Segurança", 1)[0]
    for tag in re.findall(r"<img [^>]+>", secao):
        assert 'loading="lazy"' in tag, f"sem lazy: {tag[:80]}"
        m = re.search(r'alt="([^"]*)"', tag)
        assert m and len(m.group(1)) >= 25, f"alt fraco: {tag[:80]}"
        assert 'width="' in tag and 'height="' in tag, f"sem dimensões: {tag[:80]}"


# 5. usabilidades reais citadas (não promessas): gate, roteador, health
def test_usabilidades_reais_na_secao():
    secao = _html().split('id="painel"', 1)[1].split("<!-- Segurança", 1)[0]
    for trecho in ("token", "nomos painel", "health/", "127.0.0.1"):
        assert trecho in secao, f"seção painel sem menção a {trecho!r}"
