"""Site — seção #prova (evidências) e o card do Motor Council.

A lei da casa vale para o marketing: cada número/afirmação nova tem de estar
presente e ser verdadeira. Estas travas garantem que a prova técnica, os
terminais reais e o Motor Council não somem nem regridem — e que o número de
testes anunciado NUNCA supere a realidade do repositório.
"""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SITE = (RAIZ / "site" / "index.html").read_text(encoding="utf-8")


def _secao_prova() -> str:
    partes = SITE.split('id="prova"', 1)
    assert len(partes) == 2, "site sem seção #prova"
    return partes[1].split("</section>", 1)[0]


# --------------------------------------------------------------------------
# 1. seção existe e está ligada na navegação
# --------------------------------------------------------------------------
def test_prova_ligada_na_navegacao():
    nav = SITE.split("<main", 1)[0]
    assert 'href="#prova"' in nav, "nav sem link p/ #prova"


# --------------------------------------------------------------------------
# 2. strip de prova técnica: CI, testes, telemetria, invariantes
# --------------------------------------------------------------------------
def test_prova_strip_tecnica():
    prova = _secao_prova()
    assert "12/12" in prova                       # matriz de CI
    assert "3.10" in prova and "3.13" in prova    # faixa de Python
    assert "SEC-01" in prova                       # invariantes = testes
    assert "mypy" in prova
    # telemetria zero declarada como política, não botão
    assert "telemetria" in prova


# --------------------------------------------------------------------------
# 3. terminais REAIS embutidos (evidência, não promessa)
# --------------------------------------------------------------------------
def test_prova_tem_saida_real_do_doutor():
    prova = _secao_prova()
    for marca in ("nomos doutor", "STATUS GERAL", "Modo só-local LIGADO",
                  "Auditoria íntegra", "PARCIAL"):
        assert marca in prova, f"terminal do doutor sem {marca!r}"


def test_prova_tem_saida_real_do_mcp_exemplos():
    prova = _secao_prova()
    assert "nomos mcp exemplos" in prova
    assert "[A3]" in prova                          # o gate impresso
    for canal in ("email-smtp", "telegram-bot", "whatsapp-cloud"):
        assert canal in prova, f"terminal mcp sem {canal}"


def test_prova_honestidade_parcial_explicada():
    # o "PARCIAL" tem de vir com a moldura de honestidade (nunca finge)
    prova = _secao_prova()
    assert "nunca finge" in prova or "admite" in prova


# --------------------------------------------------------------------------
# 4. Motor Council presente e honesto (dry-run / fail-closed)
# --------------------------------------------------------------------------
def test_site_mostra_motor_council():
    assert "Motor Council" in SITE
    assert "nomos conselho simular" in SITE
    assert "fail-closed" in SITE


# --------------------------------------------------------------------------
# 5. marketing NÃO pode superar a realidade: o nº de testes anunciado no hero
#    tem de ser <= nº real de funções `def test_` no repositório.
# --------------------------------------------------------------------------
def test_numero_de_testes_anunciado_nao_supera_a_realidade():
    m = re.search(r"<b>([\d.]+)\+?</b><span>testes automatizados", SITE)
    assert m, "hero sem a estatística de testes"
    anunciado = int(m.group(1).replace(".", ""))
    reais = 0
    for arq in (RAIZ / "tests").rglob("test_*.py"):
        reais += len(re.findall(r"^\s*def test_", arq.read_text(encoding="utf-8"), re.M))
    assert reais >= anunciado, f"anuncia {anunciado} testes, mas só há {reais} def test_"
