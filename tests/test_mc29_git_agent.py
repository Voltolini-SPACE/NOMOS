"""MC29 — Git Agent seguro: leitura, diagnóstico e sugestão; incapaz de mutar.

Roda o agente de verdade contra o próprio repo e contra fixtures, e prova os
contratos: allowlist de leitura, ausência de push/commit, nenhuma mutação do
working tree, sugestão proposal-only e handoff como única escrita explícita.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
AGENT = ROOT / "tools" / "nomos_git_agent.py"


def _run(args, cwd=ROOT):
    return subprocess.run(
        [sys.executable, str(AGENT), *args],
        capture_output=True, text=True, cwd=str(cwd), timeout=60,
    )


def _load():
    spec = importlib.util.spec_from_file_location("nomos_git_agent_t", AGENT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git_status(cwd=ROOT) -> str:
    return subprocess.run(["git", "status", "--short"], capture_output=True,
                          text=True, cwd=str(cwd), timeout=30).stdout


# 1. --version e --check no repo real
def test_version_dinamica():
    proc = _run(["--version"])
    assert proc.returncode == 0
    assert proc.stdout.strip() == _load().AGENT_VERSION


def test_check_json_campos_estaveis_e_sem_mutacao():
    antes = _git_status()
    proc = _run(["--check", "--json"])
    depois = _git_status()
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    for campo in ("agent_version", "mode", "is_repo", "branch", "head", "clean",
                  "modificados", "untracked", "ruido", "read_only",
                  "mutations_enabled", "auto_push_enabled",
                  "human_approval_required"):
        assert campo in data, f"campo {campo} sumiu do contrato"
    assert data["is_repo"] is True
    assert data["read_only"] is True
    assert data["mutations_enabled"] is False
    assert data["auto_push_enabled"] is False
    assert data["human_approval_required"] is True
    assert antes == depois, "--check mutou o working tree"


def test_check_fora_de_repo_sai_um(tmp_path):
    proc = _run(["--check", "--repo", str(tmp_path)])
    assert proc.returncode == 1


# 2. allowlist de leitura é fail-closed
def test_allowlist_recusa_verbo_mutante(tmp_path):
    mod = _load()
    with pytest.raises(PermissionError):
        mod._git_ro(ROOT, "commit", "-m", "x")
    with pytest.raises(PermissionError):
        mod._git_ro(ROOT, "push")
    assert "commit" not in mod._GIT_LEITURA and "push" not in mod._GIT_LEITURA


def test_codigo_nao_contem_git_push_nem_flags_de_mutacao():
    codigo = AGENT.read_text(encoding="utf-8")
    assert "git push" not in codigo
    for flag in ("--push", "--commit", "--apply"):
        assert f'"{flag}"' not in codigo, f"flag de mutação exposta: {flag}"


def test_argparse_recusa_push_desconhecido():
    proc = _run(["--push"])
    assert proc.returncode != 0


# 3. --suggest é proposal-only
def _repo_fixture(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], timeout=30, check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"],
                   timeout=30, check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"],
                   timeout=30, check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], timeout=30, check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "init"],
                   timeout=30, check=True)
    return tmp_path


def test_suggest_em_tree_suja_propoe_sem_commitar(tmp_path):
    repo = _repo_fixture(tmp_path)
    (repo / "src" / "novo.py").write_text("y = 2\n", encoding="utf-8")
    (repo / "src" / "a.py").write_text("x = 42\n", encoding="utf-8")
    proc = _run(["--suggest", "--json", "--repo", str(repo)])
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["proposal_only"] is True and data["mutations_enabled"] is False
    assert data["has_suggestion"] is True
    assert data["titulo"].startswith("feat(src)")
    # nada foi commitado: a tree continua suja
    assert _git_status(repo).strip() != ""


def test_suggest_em_tree_limpa_diz_nada_a_commitar(tmp_path):
    repo = _repo_fixture(tmp_path)
    proc = _run(["--suggest", "--repo", str(repo)])
    assert proc.returncode == 0
    assert "nada a commitar" in proc.stdout


def test_suggest_avisa_sobre_ruido(tmp_path):
    repo = _repo_fixture(tmp_path)
    (repo / ".DS_Store").write_text("lixo", encoding="utf-8")
    proc = _run(["--suggest", "--json", "--repo", str(repo)])
    data = json.loads(proc.stdout)
    assert any(".DS_Store" in linha for linha in data["corpo"])


# 4. --handoff gera pacote de evidências verificável (única escrita, explícita)
def test_handoff_gera_pacote_verificavel(tmp_path):
    repo = _repo_fixture(tmp_path)
    destino = tmp_path / "handoff"
    proc = _run(["--handoff", str(destino), "--repo", str(repo)])
    assert proc.returncode == 0, proc.stderr
    pacotes = list(destino.glob("EVIDENCIA_*"))
    assert len(pacotes) == 1
    assert (pacotes[0] / "SHA256SUMS").is_file()
    assert "OK ✓" in proc.stdout
