"""Testes reais do site NOMOS polido (assets, SEO, acessibilidade, preview).

Validam de verdade: assets existem, index/404 parseiam, links/assets locais resolvem,
SEO (og:image, twitter card, canonical, theme-color), acessibilidade básica
(1 h1, main, skip-link, lang), PNG do og-image com dimensões corretas, e o script
site/preview.py --check saindo 0 sem escrever/rede.
"""
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
INDEX = SITE / "index.html"
NOT_FOUND = SITE / "404.html"
PREVIEW = SITE / "preview.py"
FAVICON = SITE / "assets" / "favicon.svg"
OG_PNG = SITE / "assets" / "og-image.png"
OG_SVG = SITE / "assets" / "og-image.svg"

# Paleta do Brandbook v1.0 (congelado) — trava a identidade correta
NEON = "#5AF78E"
BG_TERMINAL = "#0A0F0D"


class _P(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.metas = []
        self.links = []
        self.local_refs = []
        self.h1 = 0
        self.imgs_sem_alt = 0
        self.html_lang = None

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        d = dict(attrs)
        if tag == "html":
            self.html_lang = d.get("lang")
        if tag == "h1":
            self.h1 += 1
        if tag == "meta":
            self.metas.append(d)
        if tag == "link":
            self.links.append(d)
        if tag == "img" and not d.get("alt"):
            self.imgs_sem_alt += 1
        for a in ("href", "src"):
            v = d.get(a)
            if v and not v.startswith(("http://", "https://", "#", "mailto:", "data:")):
                self.local_refs.append(v)


def _parse(p: Path) -> _P:
    ex = _P()
    ex.feed(p.read_text(encoding="utf-8"))
    return ex


# ---- existência de assets ----
def test_assets_existem_e_nao_vazios():
    for p in (FAVICON, OG_PNG, OG_SVG, INDEX, NOT_FOUND, PREVIEW):
        assert p.exists(), f"ausente: {p}"
        assert p.stat().st_size > 0, f"vazio: {p}"


def test_favicon_svg_valido():
    txt = FAVICON.read_text(encoding="utf-8")
    assert "<svg" in txt and "</svg>" in txt


def test_og_image_png_1200x630():
    # lê o header PNG (IHDR) sem dependências: bytes 16..24 = largura, altura
    data = OG_PNG.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "não é um PNG válido"
    largura = int.from_bytes(data[16:20], "big")
    altura = int.from_bytes(data[20:24], "big")
    assert (largura, altura) == (1200, 630), f"dimensões {largura}x{altura}"


# ---- HTML parseável ----
def test_index_parseavel_estrutura():
    ex = _parse(INDEX)
    for t in ("html", "head", "body", "main", "header", "footer"):
        assert t in ex.tags, f"index sem <{t}>"


def test_404_parseavel():
    ex = _parse(NOT_FOUND)
    assert "html" in ex.tags and "body" in ex.tags


# ---- SEO ----
def test_index_seo_meta():
    ex = _parse(INDEX)
    props = {m.get("property") for m in ex.metas}
    names = {m.get("name") for m in ex.metas}
    assert "og:title" in props
    assert "og:image" in props
    assert "og:image:width" in props and "og:image:height" in props
    assert "twitter:card" in names
    assert "description" in names
    assert "theme-color" in names
    rels = {(link.get("rel") or "") for link in ex.links}
    assert any("canonical" in r for r in rels), "sem <link rel=canonical>"
    assert any("icon" in r for r in rels), "sem <link rel=icon>"


def test_index_og_image_aponta_para_asset_existente():
    ex = _parse(INDEX)
    og = [m for m in ex.metas if m.get("property") == "og:image"]
    assert og, "sem og:image"
    url = og[0]["content"]
    # o caminho do og:image deve terminar em assets/og-image.png (que existe)
    assert url.endswith("assets/og-image.png")
    assert OG_PNG.exists()


# ---- acessibilidade ----
def test_index_acessibilidade_basica():
    ex = _parse(INDEX)
    assert ex.h1 == 1, f"deve haver exatamente 1 <h1> (tem {ex.h1})"
    assert ex.html_lang == "pt-BR"
    assert "main" in ex.tags
    assert ex.imgs_sem_alt == 0, "toda <img> precisa de alt"
    txt = INDEX.read_text(encoding="utf-8")
    assert "skip-link" in txt, "sem skip-link"
    assert "Pular para o conteúdo" in txt


# ---- links locais resolvem (index e 404) ----
def test_links_locais_resolvem():
    for page in (INDEX, NOT_FOUND):
        ex = _parse(page)
        quebrados = []
        for ref in ex.local_refs:
            alvo = (page.parent / ref).resolve()
            if not alvo.exists():
                quebrados.append(ref)
        assert not quebrados, f"{page.name}: refs quebradas {quebrados}"


# ---- sem secrets no site ----
def test_site_sem_segredos():
    pats = ["sk-" + "live", "ghp_" + "x", "AKIA", "-----BEGIN", "xoxb-", "AIza"]
    for p in (INDEX, NOT_FOUND, SITE / "README.md", PREVIEW):
        txt = p.read_text(encoding="utf-8", errors="ignore")
        for pat in pats:
            assert pat not in txt, f"possível segredo em {p.name}: {pat}"


# ---- script de preview --check roda e sai 0 ----
def test_preview_check_exit_zero():
    proc = subprocess.run(
        [sys.executable, str(PREVIEW), "--check"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "OK" in proc.stdout


def test_index_fiel_ao_brandbook_congelado():
    """Trava a identidade congelada: verde-neon, fundo terminal, monospace, logo ASCII."""
    txt = INDEX.read_text(encoding="utf-8")
    assert NEON in txt, "site deve usar o verde-neon congelado #5AF78E"
    assert BG_TERMINAL in txt, "site deve usar o fundo terminal congelado #0A0F0D"
    assert "monospace" in txt, "tipografia do brandbook é monospace"
    assert "#1B73E8" not in txt, "cor azul inventada não pode voltar"
    # logo ASCII em blocos (caractere de bloco cheio)
    assert "█" in txt, "hero deve conter o logo ASCII em blocos"
    # tagline e assinatura canônicas
    assert "Seu agente. Sua máquina. Suas regras." in txt
    assert "local por lei" in txt


def test_index_tem_secoes_ricas():
    """Trava as seções expandidas: recursos, motores, agentes, skills, segurança A0–A6."""
    txt = INDEX.read_text(encoding="utf-8")
    for ancora in ['id="recursos"', 'id="motores"', 'id="agentes"',
                   'id="skills"', 'id="seguranca"', 'id="como"', 'id="instalar"']:
        assert ancora in txt, f"landing sem seção: {ancora}"


def test_index_capacidades_reais_presentes():
    """Capacidades REAIS do NOMOS aparecem (ancoradas no código, não inventadas)."""
    txt = INDEX.read_text(encoding="utf-8")
    for termo in ["Ollama", "Whisper", "Stable Diffusion", "ComfyUI", "Piper",
                  "pesquisador-local", "roteador", "FTS5", "dry-run", "HMAC",
                  "Arbitragem", "arbitrar"]:
        assert termo in txt, f"landing sem capacidade real: {termo}"
    # escada de risco A0..A6
    for nivel in ["A0", "A2", "A5", "A6"]:
        assert nivel in txt, f"landing sem nível de risco {nivel}"


def test_index_honesto_sem_promessa_exagerada():
    """Regra 5 do brandbook: sem promessa exagerada de segurança absoluta."""
    txt = INDEX.read_text(encoding="utf-8").lower()
    proibidos = ["100% seguro", "impossível hackear", "impossivel hackear",
                 "segurança absoluta", "seguranca absoluta", "inviolável", "inviolavel"]
    achados = [p for p in proibidos if p in txt]
    assert not achados, f"promessa exagerada na landing: {achados}"
    # cloud deve ser apresentada como opt-in
    assert "opt-in" in txt


def test_theme_color_e_terminal():
    ex = _parse(INDEX)
    tc = [m for m in ex.metas if m.get("name") == "theme-color"]
    assert tc and tc[0]["content"] == BG_TERMINAL


def test_brandbook_congelado_presente_e_integro():
    """O brandbook congelado deve estar no repo e bater com o SHA256 do freeze."""
    import hashlib
    frozen = ROOT / "docs" / "brand" / "frozen"
    sums = frozen / "SHA256SUMS"
    assert sums.exists(), "SHA256SUMS do congelado ausente no repo"
    for linha in sums.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha:
            continue
        esperado, nome = linha.split()[0], linha.split()[-1]
        alvo = frozen / nome
        assert alvo.exists(), f"arquivo congelado ausente: {nome}"
        real = hashlib.sha256(alvo.read_bytes()).hexdigest()
        assert real == esperado, f"congelado alterado (SHA divergente): {nome}"


def test_preview_check_nao_escreve(tmp_path):
    # roda --check e confirma que nenhum arquivo do site mudou (mtimes preservados)
    import os
    antes = {p: p.stat().st_mtime for p in SITE.rglob("*") if p.is_file()}
    subprocess.run([sys.executable, str(PREVIEW), "--check"],
                   capture_output=True, text=True, cwd=str(ROOT), timeout=60)
    depois = {p: p.stat().st_mtime for p in SITE.rglob("*") if p.is_file()}
    assert antes == depois, "preview --check não pode modificar arquivos do site"
    assert os.path.isdir(SITE)
