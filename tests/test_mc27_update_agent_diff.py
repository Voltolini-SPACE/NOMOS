"""MC27 — Testes reais do gate CI read-only e do modo --diff (proposal-only).

Executam o script de verdade e validam --version (MC27.0), preservação do --check,
os novos modos --diff / --diff --json (proposta apenas, sem escrita), --apply bloqueado,
ausência de primitivas de execução e nenhuma mutação no repositório.
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
    spec = importlib.util.spec_from_file_location("nomos_update_agent_mc27", AGENT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# 1. --version imprime a versão corrente do agente (dinâmico: sem travar em bump)
def test_version_mc27():
    proc = _run(["--version"])
    assert proc.returncode == 0
    assert proc.stdout.strip() == _load_agent_module().AGENT_VERSION


# 2. --check continua imprimindo CONSISTENTE
def test_check_consistente():
    proc = _run(["--check"])
    assert proc.returncode == 0, proc.stderr
    assert "CONSISTENTE" in proc.stdout


# 3. --check --json é JSON válido
def test_check_json_valido():
    proc = _run(["--check", "--json"])
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert isinstance(data, dict)


# 4. --check --json contém agent_version = MC27.0 (+ campos MC27)
def test_check_json_campos_mc27():
    proc = _run(["--check", "--json"])
    data = json.loads(proc.stdout)
    assert data["agent_version"] == _load_agent_module().AGENT_VERSION
    assert data["mode"] == "check"
    assert data["consistent"] is True
    assert data["real_execution_enabled"] is False
    assert data["auto_push_enabled"] is False
    assert data["diff_proposer_available"] is True
    assert data["checks_total"] == data["checks_passed"]
    assert data["checks_failed"] == 0


# 5. --diff sai 0
def test_diff_exit_zero():
    proc = _run(["--diff"])
    assert proc.returncode == 0, proc.stderr


# 6. --diff contém PROPOSTA_DIFF_ONLY
def test_diff_marcador_proposta():
    proc = _run(["--diff"])
    assert "PROPOSTA_DIFF_ONLY" in proc.stdout


# 7. --diff contém NO_WRITE
def test_diff_marcador_no_write():
    proc = _run(["--diff"])
    assert "NO_WRITE" in proc.stdout
    assert "HUMAN_APPROVAL_REQUIRED" in proc.stdout


# 8. --diff --json é JSON válido
def test_diff_json_valido():
    proc = _run(["--diff", "--json"])
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert isinstance(data, dict)
    assert isinstance(data["patches"], list)


# 9. --diff --json contém proposal_only = true
def test_diff_json_proposal_only():
    proc = _run(["--diff", "--json"])
    data = json.loads(proc.stdout)
    assert data["proposal_only"] is True
    assert data["agent_version"] == _load_agent_module().AGENT_VERSION
    assert data["mode"] == "diff"


# 10. --diff --json contém writes_enabled = false
def test_diff_json_writes_disabled():
    proc = _run(["--diff", "--json"])
    data = json.loads(proc.stdout)
    assert data["writes_enabled"] is False
    assert data["human_approval_required"] is True


# 10b. patches, se houver, têm estrutura correta e sem comandos/segredos
def test_diff_patches_estruturados_e_seguros():
    proc = _run(["--diff", "--json"])
    data = json.loads(proc.stdout)
    for p in data["patches"]:
        assert set(p.keys()) >= {"path", "reason", "risk", "proposal"}
        blob = json.dumps(p).lower()
        for proibido in ["subprocess", "os.system", "git push", "rm -rf", "sk-", "ghp_"]:
            assert proibido not in blob, f"patch contem termo proibido: {proibido}"


# 11. --apply continua bloqueado (todas as variações)
def test_apply_bloqueado():
    assert _run(["--apply"]).returncode != 0
    assert _run(["--apply", "--i-understand-this-is-disabled"]).returncode != 0
    assert _run(["--apply", "--i-understand-this-writes-files"]).returncode != 0


def test_apply_informa_desabilitado():
    proc = _run(["--apply"])
    assert "desabilitada" in proc.stdout.lower() or "requer" in proc.stdout.lower()


# 12-15. Ausência de primitivas de execução no código do agente
def test_agente_sem_primitivas_de_execucao():
    codigo = AGENT.read_text(encoding="utf-8")
    assert "subprocess" not in codigo
    assert "os.system" not in codigo
    assert "Popen" not in codigo
    assert "popen" not in codigo
    assert "twine" not in codigo.lower()
    assert "check_output" not in codigo


# 16. Modo --diff não muta o repositório
def _tree_hash():
    proc = subprocess.run(["git", "status", "--short"],
                          capture_output=True, text=True, cwd=str(ROOT))
    return hashlib.sha256(proc.stdout.encode()).hexdigest()


def test_diff_nao_muta_repositorio():
    antes = _tree_hash()
    _run(["--diff"])
    _run(["--diff", "--json"])
    depois = _tree_hash()
    assert antes == depois, "--diff nao pode alterar o repositorio"


# 17. Fail-closed do check via módulo (diretório sem deliverables)
def test_check_failclosed_em_repo_vazio(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/x\n", encoding="utf-8")
    mod = _load_agent_module()
    agent = mod.NomosUpdateAgent(tmp_path)
    report = agent.run_check()
    assert report.status == "inconsistent"


# 18. run_diff é read-only mesmo em repo temporário (não cria arquivos)
def test_diff_readonly_em_tmp(tmp_path):
    mod = _load_agent_module()
    agent = mod.NomosUpdateAgent(tmp_path)
    proposal = agent.run_diff()
    assert proposal["proposal_only"] is True
    assert proposal["writes_enabled"] is False
    # nenhum arquivo criado no tmp
    assert list(tmp_path.iterdir()) == []
