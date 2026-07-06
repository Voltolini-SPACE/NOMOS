"""MC29 — Brand + Site Sync Agent: checks de marca no NOMOS Update Agent.

Prova, com execução real do agente, que o `--check` agora detecta deriva de
marca: paleta congelada ausente do site, tagline não-canônica, recomendação de
`pip install nomos` puro (pacote de terceiros no PyPI) e versão incoerente
entre pyproject e pacote. Positivo no repo real; negativos em fixtures.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT = ROOT / "tools" / "nomos_update_agent.py"


def _run(args, cwd=ROOT):
    return subprocess.run(
        [sys.executable, str(AGENT), *args],
        capture_output=True, text=True, cwd=str(cwd), timeout=60,
    )


def _load_agent_module():
    spec = importlib.util.spec_from_file_location("nomos_update_agent_mc29", AGENT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _nomes_dos_checks(agent) -> dict:
    return {c.name: c for c in agent.report.checks}


# ---------------------------------------------------------------------------
# Positivo: o repositório real está alinhado com a marca
# ---------------------------------------------------------------------------
def test_check_real_inclui_checks_de_marca_e_passa():
    proc = _run(["--check", "--json"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)
    nomes = [c["name"] for c in data["checks"]]
    for esperado in ("brand:paleta", "brand:tagline",
                     "brand:instalacao_oficial", "brand:versao_coerente"):
        assert esperado in nomes, f"check {esperado} não roda no --check"
    assert data["consistent"] is True


# ---------------------------------------------------------------------------
# Negativos: fixtures com deriva de marca são detectadas
# ---------------------------------------------------------------------------
def _repo_fixture(tmp_path: Path) -> Path:
    """Réplica mínima dos deliverables usados pelos checks de marca."""
    (tmp_path / "docs/brand").mkdir(parents=True)
    (tmp_path / "docs/installation").mkdir(parents=True)
    (tmp_path / "site").mkdir()
    (tmp_path / "src/nomos").mkdir(parents=True)
    (tmp_path / "README.md").write_text(
        "# X\nSeu agente. Sua máquina. Suas regras.\nlocal por lei\n",
        encoding="utf-8")
    (tmp_path / "site/index.html").write_text(
        "<html>Seu agente. Sua máquina. Suas regras. local por lei "
        "#5AF78E #0A0F0D</html>", encoding="utf-8")
    (tmp_path / "docs/brand/NOMOS_BRANDBOOK.md").write_text("brand", encoding="utf-8")
    (tmp_path / "docs/installation/NOMOS_INSTALLATION_MANUAL.md").write_text(
        "manual", encoding="utf-8")
    (tmp_path / "docs/INSTALL.md").write_text("install", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('version = "1.0.0"\n', encoding="utf-8")
    (tmp_path / "src/nomos/__init__.py").write_text(
        '__version__ = "1.0.0"\n', encoding="utf-8")
    return tmp_path


def test_fixture_alinhada_passa_nos_checks_de_marca(tmp_path):
    mod = _load_agent_module()
    agent = mod.NomosUpdateAgent(_repo_fixture(tmp_path))
    agent._check_brand_paleta()
    agent._check_brand_tagline()
    agent._check_instalacao_oficial()
    agent._check_versao_coerente()
    nomes = _nomes_dos_checks(agent)
    assert all(c.ok for c in nomes.values()), agent.report.errors


def test_paleta_ausente_no_site_falha(tmp_path):
    raiz = _repo_fixture(tmp_path)
    (raiz / "site/index.html").write_text(
        "<html>Seu agente. Sua máquina. Suas regras. local por lei "
        "cor errada #123456</html>", encoding="utf-8")
    mod = _load_agent_module()
    agent = mod.NomosUpdateAgent(raiz)
    agent._check_brand_paleta()
    assert _nomes_dos_checks(agent)["brand:paleta"].ok is False


def test_tagline_nao_canonica_falha(tmp_path):
    raiz = _repo_fixture(tmp_path)
    (raiz / "README.md").write_text("# X\nUm agente qualquer.\n", encoding="utf-8")
    mod = _load_agent_module()
    agent = mod.NomosUpdateAgent(raiz)
    agent._check_brand_tagline()
    assert _nomes_dos_checks(agent)["brand:tagline"].ok is False


def test_pip_install_nomos_puro_e_detectado(tmp_path):
    raiz = _repo_fixture(tmp_path)
    (raiz / "docs/INSTALL.md").write_text(
        "Instale com:\n\n    pip install nomos\n", encoding="utf-8")
    mod = _load_agent_module()
    agent = mod.NomosUpdateAgent(raiz)
    agent._check_instalacao_oficial()
    check = _nomes_dos_checks(agent)["brand:instalacao_oficial"]
    assert check.ok is False and "docs/INSTALL.md" in check.detail


def test_formas_legitimas_de_pip_nao_sao_falso_positivo(tmp_path):
    raiz = _repo_fixture(tmp_path)
    (raiz / "docs/INSTALL.md").write_text(
        "pip install nomos-1.0.0-py3-none-any.whl\n"
        "pip install nomos-<versão>-py3-none-any.whl\n"
        "pip install git+https://github.com/Voltolini-SPACE/NOMOS\n"
        "pip install nomos.tar.gz\n", encoding="utf-8")
    mod = _load_agent_module()
    agent = mod.NomosUpdateAgent(raiz)
    agent._check_instalacao_oficial()
    assert _nomes_dos_checks(agent)["brand:instalacao_oficial"].ok is True


def test_versao_incoerente_falha(tmp_path):
    raiz = _repo_fixture(tmp_path)
    (raiz / "src/nomos/__init__.py").write_text(
        '__version__ = "9.9.9"\n', encoding="utf-8")
    mod = _load_agent_module()
    agent = mod.NomosUpdateAgent(raiz)
    agent._check_versao_coerente()
    check = _nomes_dos_checks(agent)["brand:versao_coerente"]
    assert check.ok is False and "9.9.9" in check.detail


# ---------------------------------------------------------------------------
# Segurança preservada (contratos do agente não regridem com o MC29)
# ---------------------------------------------------------------------------
def test_agente_segue_read_only_e_sem_push():
    codigo = AGENT.read_text(encoding="utf-8")
    assert "git push" not in codigo
    proc = _run(["--check", "--json"])
    data = json.loads(proc.stdout)
    assert data["real_execution_enabled"] is False
    assert data["auto_push_enabled"] is False
    assert data["human_approval_required"] is True
