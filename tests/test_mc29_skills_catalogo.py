"""MC29 — Catálogo de capacidades: o usuário entende o que o NOMOS sabe fazer.

Contrato: cada skill vira entrada com 8 campos (nome, descricao, entrada,
saida, risco, status, permissoes, exemplos); instaladas vêm antes; catálogo é
somente leitura; CLI expõe humano e --json estável.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

from nomos.ext import skill_catalogo as scat

ROOT = Path(__file__).resolve().parent.parent
EXEMPLO = ROOT / "examples" / "skills" / "busca-arquivos"


def _instalar_exemplo(home: Path, nome="busca-arquivos") -> Path:
    skills_dir = home / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(EXEMPLO, skills_dir / nome)
    return skills_dir


# 1. os 8 campos do contrato, com valores derivados do manifesto real
def test_capacidades_tem_os_oito_campos(tmp_path):
    skills_dir = _instalar_exemplo(tmp_path)
    caps = scat.capacidades(tmp_path, skills_dir)
    assert len(caps) == 1
    cap = caps[0]
    assert tuple(sorted(cap)) == tuple(sorted(scat.CAMPOS))
    assert cap["nome"] == "busca-arquivos"
    assert cap["status"] == "instalada"
    assert cap["permissoes"] == ["A0_READ_LOCAL"]
    assert cap["risco"]  # risco sempre visível (derivado das permissões)
    assert cap["exemplos"], "keywords do manifesto viram exemplos"
    assert cap["entrada"] and cap["saida"]


# 2. skills_dir vazio/ausente => catálogo vazio, sem erro
def test_catalogo_vazio_sem_erro(tmp_path):
    assert scat.capacidades(tmp_path, tmp_path / "skills") == []


# 3. manifesto ilegível não derruba o catálogo (fail-soft na leitura)
def test_manifesto_corrompido_nao_derruba(tmp_path):
    skills_dir = _instalar_exemplo(tmp_path)
    quebrada = skills_dir / "quebrada"
    quebrada.mkdir()
    (quebrada / "skill.json").write_text("{ nao é json", encoding="utf-8")
    caps = scat.capacidades(tmp_path, skills_dir)
    assert [c["nome"] for c in caps] == ["busca-arquivos"]


# 4. instaladas vêm antes das disponíveis; nomes não duplicam
def test_instalada_vence_disponivel_e_ordena(tmp_path):
    skills_dir = _instalar_exemplo(tmp_path)
    caps = scat.capacidades(tmp_path, skills_dir)
    assert all(c["status"] == "instalada" for c in caps[:1])
    nomes = [c["nome"] for c in caps]
    assert len(nomes) == len(set(nomes))


# 5. CLI real
def _cli(args, home: Path):
    return subprocess.run(
        [sys.executable, "-m", "nomos", *args],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT),
        env={"NOMOS_HOME": str(home), "PATH": ""},
    )


def test_cli_catalogo_json_estavel(tmp_path):
    _instalar_exemplo(tmp_path)
    proc = _cli(["skills", "catalogo", "--json"], tmp_path)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["contrato"] == scat.CONTRATO_CATALOGO == 1
    assert data["capacidades"][0]["nome"] == "busca-arquivos"


def test_cli_catalogo_humano_mostra_risco_e_permissoes(tmp_path):
    _instalar_exemplo(tmp_path)
    proc = _cli(["skills", "catalogo"], tmp_path)
    assert proc.returncode == 0
    assert "busca-arquivos" in proc.stdout
    assert "risco" in proc.stdout and "permissões" in proc.stdout


def test_cli_catalogo_vazio_orienta(tmp_path):
    proc = _cli(["skills", "catalogo"], tmp_path)
    assert proc.returncode == 0
    assert "nenhuma skill" in proc.stdout
