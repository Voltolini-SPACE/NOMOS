"""MC30 — Onda A: o guardião propõe (A1) e as evidências ganham `listar` (A2).

A1: `--diff` do update agent deixa de só acusar deriva de marca — cada check
`brand:*` reprovado vem com proposta de correção (proposal-only, sem escrever).
A2: `nomos evidencia listar [--json]` mostra todos os pacotes com verificação
REAL de integridade.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT = ROOT / "tools" / "nomos_update_agent.py"


def _load_agent():
    spec = importlib.util.spec_from_file_location("nomos_update_agent_mc30", AGENT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _repo_fixture(tmp_path: Path) -> Path:
    (tmp_path / "docs/brand").mkdir(parents=True)
    (tmp_path / "docs/installation").mkdir(parents=True)
    (tmp_path / "docs/governance").mkdir(parents=True)
    (tmp_path / "site").mkdir()
    (tmp_path / "src/nomos").mkdir(parents=True)
    (tmp_path / "README.md").write_text(
        "Seu agente. Sua máquina. Suas regras. local por lei "
        "NOMOS_INSTALLATION_MANUAL NOMOS_BRANDBOOK", encoding="utf-8")
    (tmp_path / "site/index.html").write_text(
        "<html>Seu agente. Sua máquina. Suas regras. local por lei "
        "#5AF78E #0A0F0D</html>", encoding="utf-8")
    (tmp_path / "docs/brand/NOMOS_BRANDBOOK.md").write_text("b", encoding="utf-8")
    (tmp_path / "docs/installation/NOMOS_INSTALLATION_MANUAL.md").write_text(
        "m", encoding="utf-8")
    (tmp_path / "docs/INSTALL.md").write_text("i", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('version = "1.0.0"\n', encoding="utf-8")
    (tmp_path / "src/nomos/__init__.py").write_text(
        '__version__ = "1.0.0"\n', encoding="utf-8")
    mod = _load_agent()
    (tmp_path / "docs/governance/NOMOS_UPDATE_AGENT.md").write_text(
        f"governança {mod.AGENT_VERSION}", encoding="utf-8")
    return tmp_path


# ----------------------------------------------------------------- A1
def test_a1_diff_sem_deriva_nao_propoe_patch_de_marca(tmp_path):
    mod = _load_agent()
    agent = mod.NomosUpdateAgent(_repo_fixture(tmp_path))
    patches = agent.run_diff()["patches"]
    assert not [p for p in patches if p["reason"] == "deriva_de_marca"]


def test_a1_diff_propoe_correcao_para_cada_deriva(tmp_path):
    raiz = _repo_fixture(tmp_path)
    # quebra 3 contratos de marca de uma vez
    (raiz / "site/index.html").write_text("<html>site sem marca</html>",
                                          encoding="utf-8")
    (raiz / "docs/INSTALL.md").write_text("pip install nomos\n", encoding="utf-8")
    (raiz / "src/nomos/__init__.py").write_text('__version__ = "9.9.9"\n',
                                                encoding="utf-8")
    mod = _load_agent()
    agent = mod.NomosUpdateAgent(raiz)
    marca = {p["proposal"].split("]")[0].strip("[")
             for p in agent.run_diff()["patches"]
             if p["reason"] == "deriva_de_marca"}
    assert {"brand:paleta", "brand:tagline", "brand:instalacao_oficial",
            "brand:versao_coerente"} <= marca


def test_a1_diff_continua_proposal_only(tmp_path):
    raiz = _repo_fixture(tmp_path)
    (raiz / "docs/INSTALL.md").write_text("pip install nomos\n", encoding="utf-8")
    antes = {p: (raiz / p).read_text(encoding="utf-8")
             for p in ("docs/INSTALL.md", "README.md", "site/index.html")}
    mod = _load_agent()
    proposta = mod.NomosUpdateAgent(raiz).run_diff()
    assert proposta["writes_enabled"] is False
    for p, conteudo in antes.items():
        assert (raiz / p).read_text(encoding="utf-8") == conteudo, "diff escreveu!"


# ----------------------------------------------------------------- A2
def _cli(args, home: Path):
    return subprocess.run(
        [sys.executable, "-m", "nomos", *args],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT),
        env={"NOMOS_HOME": str(home), "PATH": ""},
    )


def test_a2_listar_vazio_orienta(tmp_path):
    proc = _cli(["evidencia", "listar"], tmp_path)
    assert proc.returncode == 0 and "nenhum pacote" in proc.stdout


def test_a2_listar_mostra_integridade_real(tmp_path):
    _cli(["evidencia", "criar", "pacote bom"], tmp_path)
    _cli(["evidencia", "criar", "pacote violado"], tmp_path)
    violado = next((tmp_path / "evidencias").glob("EVIDENCIA_pacote-violado_*"))
    (violado / "RELATORIO.md").write_text("adulterado", encoding="utf-8")
    proc = _cli(["evidencia", "listar"], tmp_path)
    assert proc.returncode == 0
    assert "✅ íntegro" in proc.stdout and "❌ NÃO confere" in proc.stdout


def test_a2_listar_json_estavel(tmp_path):
    _cli(["evidencia", "criar", "m"], tmp_path)
    proc = _cli(["evidencia", "listar", "--json"], tmp_path)
    data = json.loads(proc.stdout)
    assert data["contrato"] == 1
    assert data["pacotes"][0]["integro"] is True
    assert data["pacotes"][0]["problemas"] == []
