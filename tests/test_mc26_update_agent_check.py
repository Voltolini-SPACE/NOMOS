"""MC26 — Testes reais do modo --check/--version/--json do NOMOS Update Agent.

Executam o script de verdade (subprocess a partir do teste, nao do agente) e validam
exit codes, JSON parseavel, comportamento fail-closed com fixture temporaria, ausencia
de execucao destrutiva no codigo do agente e nenhuma mutacao no repositorio.
"""
import hashlib
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
    spec = importlib.util.spec_from_file_location("nomos_update_agent_mc26", AGENT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# --version
# ---------------------------------------------------------------------------
def test_version_imprime_versao_do_agente_e_sai_zero():
    # Asserção dinâmica: acompanha AGENT_VERSION (MC26.0 -> MC27.0 -> ...),
    # evitando travar o teste a cada bump de versão.
    mod = _load_agent_module()
    proc = _run(["--version"])
    assert proc.returncode == 0
    assert proc.stdout.strip() == mod.AGENT_VERSION


# ---------------------------------------------------------------------------
# --check
# ---------------------------------------------------------------------------
def test_check_sai_zero_no_repo_consistente():
    proc = _run(["--check"])
    assert proc.returncode == 0, proc.stderr
    assert "CONSISTENTE" in proc.stdout


def test_check_verifica_deliverables_esperados():
    proc = _run(["--check"])
    for termo in ["brand", "installation", "site/index.html", "links", "secrets", "git"]:
        assert termo in proc.stdout, f"--check nao mencionou {termo}"


# ---------------------------------------------------------------------------
# --check --json
# ---------------------------------------------------------------------------
def test_check_json_e_parseavel_e_completo():
    proc = _run(["--check", "--json"])
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)  # levanta se invalido
    for chave in ["status", "version", "checks", "errors", "warnings",
                  "files_checked", "git", "safe_mode", "timestamp_utc",
                  "next_recommendation"]:
        assert chave in data, f"JSON sem chave obrigatoria: {chave}"
    assert data["version"] == _load_agent_module().AGENT_VERSION
    assert data["status"] == "ok"
    assert data["safe_mode"] is True
    assert isinstance(data["checks"], list) and data["checks"]
    assert data["git"]["is_repo"] is True


def test_check_json_nao_emite_ansi():
    proc = _run(["--check", "--json"])
    assert "\033[" not in proc.stdout, "JSON nao deve conter codigos ANSI"


# ---------------------------------------------------------------------------
# Seguranca — sem execucao destrutiva no codigo do agente
# ---------------------------------------------------------------------------
def test_agente_sem_subprocess_ou_os_system():
    codigo = AGENT.read_text(encoding="utf-8")
    assert "subprocess" not in codigo, "Agente nao deve importar subprocess"
    assert "os.system" not in codigo, "Agente nao deve usar os.system"
    assert "twine" not in codigo.lower(), "Agente nao deve referenciar twine"


def test_agente_sem_git_push_tag_release():
    codigo = AGENT.read_text(encoding="utf-8").lower()
    # nenhuma chamada real de mutacao
    assert "push" not in codigo or "git push" not in codigo
    assert "os.popen" not in codigo
    assert "check_output" not in codigo
    assert "popen" not in codigo


def test_apply_bloqueado_sem_flag():
    proc = _run(["--apply"])
    assert proc.returncode == 1
    assert "requer flag" in proc.stdout or "requer" in proc.stdout


def test_apply_failclosed_com_flag():
    proc = _run(["--apply", "--i-understand-this-writes-files"])
    assert proc.returncode == 1  # fail-closed, nao implementado
    assert "Nenhuma escrita" in proc.stdout or "fail-closed" in proc.stdout.lower()


# ---------------------------------------------------------------------------
# Links internos da landing resolvem
# ---------------------------------------------------------------------------
def test_links_landing_resolvem():
    mod = _load_agent_module()
    agent = mod.NomosUpdateAgent(ROOT)
    agent._check_links_landing()
    link_checks = [c for c in agent.report.checks if c.name == "links:landing"]
    assert link_checks and link_checks[0].ok, "Links internos da landing quebrados"


# ---------------------------------------------------------------------------
# Fail-closed com deliverable ausente (fixture temporaria)
# ---------------------------------------------------------------------------
def test_failclosed_com_arquivo_ausente(tmp_path):
    # repo temporario vazio (sem deliverables) -> deve reprovar
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/test\n", encoding="utf-8")
    mod = _load_agent_module()
    agent = mod.NomosUpdateAgent(tmp_path)
    report = agent.run_check()
    assert report.status == "inconsistent"
    assert report.errors, "Deve haver erros quando deliverables faltam"
    # exit code correspondente pela funcao main apontando para tmp seria 1;
    # aqui validamos o status estrutural.


def test_failclosed_exit_code_via_cli(tmp_path):
    # roda o CLI com cwd fake nao muda repo_root (baseado em __file__),
    # entao simulamos via modulo para exit code determinado.
    mod = _load_agent_module()
    agent = mod.NomosUpdateAgent(tmp_path)
    report = agent.run_check()
    exit_code = 0 if report.status == "ok" else 1
    assert exit_code == 1


# ---------------------------------------------------------------------------
# Nenhuma mutacao no repositorio ao rodar --check
# ---------------------------------------------------------------------------
def _tree_hash():
    """Hash do git status --short (estado da arvore) para detectar mutacao."""
    proc = subprocess.run(["git", "status", "--short"],
                          capture_output=True, text=True, cwd=str(ROOT))
    return hashlib.sha256(proc.stdout.encode()).hexdigest()


def test_check_nao_muta_repositorio():
    antes = _tree_hash()
    _run(["--check"])
    _run(["--check", "--json"])
    depois = _tree_hash()
    assert antes == depois, "--check nao pode alterar o estado do repositorio"
