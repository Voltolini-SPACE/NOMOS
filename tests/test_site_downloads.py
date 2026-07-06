"""Site — downloads reais e links íntegros (MC34).

O site é a porta de entrada: os botões de download têm de apontar para
assets que EXISTEM nas releases (install.sh / install.ps1, por tag), o
caminho git tem de estar visível, e nenhum link relativo quebrado
(``../``) pode voltar — o site é servido a partir de ``site/`` e esses
links 404avam fora do repositório.
"""
import re
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site" / "index.html"
REPO_URL = "https://github.com/Voltolini-SPACE/NOMOS"


def _html() -> str:
    return SITE.read_text(encoding="utf-8")


# 1. os três caminhos de instalação: macOS/Linux, Windows e git
def test_download_macos_linux_aponta_para_asset_de_release():
    html = _html()
    m = re.search(rf'href="{REPO_URL}/releases/download/([^"]+)/install\.sh"',
                  html)
    assert m, "botão macOS/Linux deve linkar install.sh de uma release"
    assert "bash install.sh" in html          # instrução de uso junto


def test_download_windows_aponta_para_asset_de_release():
    html = _html()
    m = re.search(rf'href="{REPO_URL}/releases/download/([^"]+)/install\.ps1"',
                  html)
    assert m, "botão Windows deve linkar install.ps1 de uma release"
    assert "PowerShell" in html


def test_caminho_git_visivel():
    html = _html()
    assert f"git clone {REPO_URL}" in html
    assert "pip install ." in html


# 2. a MESMA tag nos dois instaladores (nunca versões trocadas)
def test_tags_dos_instaladores_sao_consistentes():
    html = _html()
    tags = set(re.findall(
        rf'{REPO_URL}/releases/download/([^/"]+)/install\.(?:sh|ps1)', html))
    assert len(tags) == 1, f"tags divergentes nos downloads: {tags}"


# 3. integridade é ensinada, não escondida
def test_verificacao_de_integridade_mencionada():
    html = _html()
    assert "SHA256SUMS" in html
    assert "sha256sum --check" in html


# 4. nenhum link relativo quebrado (../) — o site vive em site/
def test_sem_links_relativos_para_fora_do_site():
    html = _html()
    quebrados = re.findall(r'href="\.\./[^"]*"', html)
    assert not quebrados, f"links relativos que 404am fora do repo: {quebrados}"


# 5. âncoras da navegação apontam para seções que existem
def test_nav_ancoras_existem_no_documento():
    html = _html()
    for anc in re.findall(r'<nav[^>]*>.*?</nav>', html, flags=re.S):
        for alvo in re.findall(r'href="#([^"]+)"', anc):
            assert (f'id="{alvo}"' in html), f"nav aponta p/ #{alvo} inexistente"


# 6. a página de todas as versões continua acessível
def test_link_para_todas_as_releases():
    assert f'{REPO_URL}/releases"' in _html()
