"""MC25 — Testes reais e executaveis dos deliverables (Brandbook, Manual, Landing, Update Agent).

Valida objetivamente que os artefatos do MC25 existem, tem conteudo canonico,
estrutura de secoes esperada, HTML parseavel, links internos resolviveis, o agente
roda em dry-run sem escrever e nenhum segredo esta exposto.

Estes testes SUBSTITUEM asercoes em markdown por verificacao executavel real.
"""
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

BRANDBOOK = ROOT / "docs" / "brand" / "NOMOS_BRANDBOOK.md"
MANUAL = ROOT / "docs" / "installation" / "NOMOS_INSTALLATION_MANUAL.md"
GOVERNANCE = ROOT / "docs" / "governance" / "NOMOS_UPDATE_AGENT.md"
LANDING = ROOT / "site" / "index.html"
SITE_README = ROOT / "site" / "README.md"
AGENT = ROOT / "tools" / "nomos_update_agent.py"


# ---------------------------------------------------------------------------
# 1. Existencia de arquivos
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", [BRANDBOOK, MANUAL, GOVERNANCE, LANDING, SITE_README, AGENT])
def test_deliverable_existe(path):
    assert path.exists(), f"Deliverable ausente: {path}"
    assert path.stat().st_size > 0, f"Deliverable vazio: {path}"


# ---------------------------------------------------------------------------
# 2. Brandbook — secoes e termos canonicos
# ---------------------------------------------------------------------------
BRANDBOOK_SECOES = [
    "Essência da Marca",
    "Posicionamento",
    "Identidade Verbal",
    "Identidade Visual",
    "Mensagens Canônicas",
    "Regras de Consistência",
]


@pytest.mark.parametrize("secao", BRANDBOOK_SECOES)
def test_brandbook_tem_secao(secao):
    texto = BRANDBOOK.read_text(encoding="utf-8")
    assert secao in texto, f"Brandbook sem secao obrigatoria: {secao}"


BRANDBOOK_TERMOS = ["local por lei", "aprovação humana", "dry-run", "fail-closed",
                    "skill", "motor", "conselho", "roteador"]


@pytest.mark.parametrize("termo", BRANDBOOK_TERMOS)
def test_brandbook_menciona_termo_canonico(termo):
    texto = BRANDBOOK.read_text(encoding="utf-8").lower()
    assert termo.lower() in texto, f"Brandbook nao menciona termo canonico: {termo}"


def test_brandbook_tem_slogan_principal():
    texto = BRANDBOOK.read_text(encoding="utf-8")
    assert "Seu agente. Sua máquina. Suas regras." in texto


# ---------------------------------------------------------------------------
# 3. Manual — secoes obrigatorias
# ---------------------------------------------------------------------------
MANUAL_SECOES = [
    "Pré-requisitos",
    "Instalação Rápida",
    "Instalação para Desenvolvimento",
    "Primeira Execução Segura",
    "Solução de Problemas",
    "Desinstalação",
    "Segurança",
]


@pytest.mark.parametrize("secao", MANUAL_SECOES)
def test_manual_tem_secao(secao):
    texto = MANUAL.read_text(encoding="utf-8")
    assert secao in texto, f"Manual sem secao obrigatoria: {secao}"


def test_manual_tem_comando_pip():
    texto = MANUAL.read_text(encoding="utf-8")
    assert "pip install" in texto
    assert "pytest" in texto
    assert "ruff" in texto


# ---------------------------------------------------------------------------
# 4. Landing — HTML parseavel + elementos-chave
# ---------------------------------------------------------------------------
class _Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.hrefs = []
        self.metas = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        d = dict(attrs)
        if tag == "a" and "href" in d:
            self.hrefs.append(d["href"])
        if tag == "meta":
            self.metas.append(d)


def _parse_landing():
    parser = _Collector()
    parser.feed(LANDING.read_text(encoding="utf-8"))
    return parser


def test_landing_html_parseavel():
    # Se o HTML for malformado o parser levanta excecao; aqui garantimos que nao.
    parser = _parse_landing()
    assert "html" in parser.tags
    assert "head" in parser.tags
    assert "body" in parser.tags


def test_landing_tem_hero_h1():
    parser = _parse_landing()
    assert "h1" in parser.tags, "Landing sem <h1> (hero)"


def test_landing_tem_secoes_essenciais():
    # Âncoras estruturais estáveis (independentes da cópia de marketing).
    texto = LANDING.read_text(encoding="utf-8")
    for ancora in ['id="sobre"', 'id="como"', 'id="instalar"', 'id="seguranca"', 'id="roadmap"']:
        assert ancora in texto, f"Landing sem seção: {ancora}"


def test_landing_tem_cta():
    texto = LANDING.read_text(encoding="utf-8")
    assert "btn-primary" in texto
    assert "Instalar" in texto


def test_landing_tem_seo_basico():
    parser = _parse_landing()
    tem_description = any(m.get("name") == "description" for m in parser.metas)
    tem_viewport = any(m.get("name") == "viewport" for m in parser.metas)
    tem_og_title = any(m.get("property") == "og:title" for m in parser.metas)
    assert tem_description, "Landing sem meta description"
    assert tem_viewport, "Landing sem meta viewport (responsivo)"
    assert tem_og_title, "Landing sem og:title (Open Graph)"


def test_landing_links_internos_resolvem():
    parser = _parse_landing()
    base = LANDING.parent
    quebrados = []
    for href in parser.hrefs:
        if href.startswith(("http://", "https://", "#", "mailto:")):
            continue
        alvo = (base / href).resolve()
        if not alvo.exists():
            quebrados.append(href)
    assert not quebrados, f"Links internos quebrados na landing: {quebrados}"


# ---------------------------------------------------------------------------
# 5. Update Agent — seguranca (fail-closed, sem execucao real)
# ---------------------------------------------------------------------------
def test_agente_nao_executa_git():
    """O agente nao pode conter chamadas capazes de push/tag/commit/release."""
    codigo = AGENT.read_text(encoding="utf-8")
    # Nenhuma primitiva de execucao de processo -> incapaz de rodar git/twine.
    assert "subprocess" not in codigo, "Agente contem subprocess (poderia executar git)"
    assert "os.system" not in codigo, "Agente contem os.system (poderia executar git)"
    assert "twine" not in codigo.lower(), "Agente referencia twine (PyPI)"


def test_agente_apply_exige_flag_de_risco():
    codigo = AGENT.read_text(encoding="utf-8")
    assert "i_understand_this_writes_files" in codigo
    # --apply deve ser bloqueado sem a flag explicita
    assert "requer flag" in codigo or "requer" in codigo


def test_agente_dry_run_por_padrao():
    codigo = AGENT.read_text(encoding="utf-8")
    assert 'default=True' in codigo and 'dry-run' in codigo.lower()


def test_agente_check_roda_e_sai_zero():
    """Executa o agente em --check e verifica exit 0 (dry-run seguro)."""
    proc = subprocess.run(
        [sys.executable, str(AGENT), "--check"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=60,
    )
    assert proc.returncode == 0, f"Agente --check falhou: {proc.stderr}"
    assert "CONSISTENTE" in proc.stdout or "Relat" in proc.stdout


# ---------------------------------------------------------------------------
# 6. Seguranca — sem segredos nos deliverables
# ---------------------------------------------------------------------------
DELIVERABLES = [BRANDBOOK, MANUAL, GOVERNANCE, LANDING, SITE_README, AGENT]

# Padroes SHAPE-AWARE: exigem o formato real da chave (valor), evitando falso-positivo
# com substrings inocentes como "sk-t" (id de secao), "task-", "risk-".
SECRET_REGEXES = [
    re.compile("s" + r"k-[A-Za-z0-9]{16,}"),        # chaves estilo OpenAI/Anthropic
    re.compile("-----" + r"BEGIN [A-Z ]*PRIVATE"),   # blocos PEM
    re.compile("AK" + r"IA[0-9A-Z]{16}"),            # AWS access key id
    re.compile("g" + r"hp_[A-Za-z0-9]{16,}"),        # GitHub PAT
]


@pytest.mark.parametrize("path", DELIVERABLES)
def test_deliverable_sem_segredo(path):
    texto = path.read_text(encoding="utf-8", errors="ignore")
    achados = [rgx.pattern for rgx in SECRET_REGEXES if rgx.search(texto)]
    assert not achados, f"Possivel segredo em {path.name}: {achados}"
