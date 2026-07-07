"""MC46.1 — cobertura de documentação/marketing dos conectores e briefing.

Trava contra o ruído "feature existe mas ninguém acha": o site, o README e
a doc dos canais têm de mencionar os conectores (Telegram/WhatsApp/e-mail),
o comando de descoberta e o briefing entregue no canal. E a doc de
conectores NÃO pode voltar a ser órfã (sem link do README ou do site).
"""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SITE = (RAIZ / "site" / "index.html").read_text(encoding="utf-8")
README = (RAIZ / "README.md").read_text(encoding="utf-8")
DOC = RAIZ / "docs" / "CONECTORES_SOCIAIS.md"


def test_site_mostra_os_tres_canais():
    secao = SITE.split('id="conexoes"', 1)
    assert len(secao) == 2, "site sem seção #conexoes"
    corpo = secao[1].split("</section>", 1)[0]
    for canal in ("Telegram", "WhatsApp", "e-mail"):
        assert canal in corpo, f"seção conexões sem {canal}"
    assert "nomos mcp exemplos" in corpo
    assert "briefing-telegram:" in corpo          # a receita real
    assert "A3" in corpo                          # a verdade do gate


def test_site_liga_a_secao_na_nav_e_no_card():
    assert 'href="#conexoes"' in SITE.split("<main", 1)[0], "nav sem conexões"
    # o card de recursos aponta para a seção
    assert SITE.count('href="#conexoes"') >= 2


def test_readme_documenta_conectores_e_briefing():
    assert "nomos mcp exemplos" in README
    assert "briefing-telegram:" in README
    for canal in ("Telegram", "WhatsApp", "e-mail"):
        assert canal in README, f"README sem {canal}"


def test_doc_conectores_nao_e_orfa():
    assert DOC.is_file()
    assert "CONECTORES_SOCIAIS.md" in README, "doc sem link no README"
    assert "CONECTORES_SOCIAIS.md" in SITE, "doc sem link no site"


def test_doc_lista_email_alem_de_telegram_whatsapp():
    texto = DOC.read_text(encoding="utf-8")
    for canal in ("Telegram", "WhatsApp", "E-mail", "SMTP"):
        assert canal in texto, f"doc dos canais sem {canal}"


def test_roadmap_do_site_reflete_conexoes():
    rm = SITE.split('id="roadmap"', 1)[1].split("</section>", 1)[0]
    assert "MC40" in rm and "Conexões" in rm      # não parou no MC32
    assert re.search(r"MC3[4-9].*Cockpit", rm), "roadmap sem a fase Cockpit"
