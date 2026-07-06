"""MC30 — A3 (doutor unificado) e A6 (códigos E011/E012 nos fluxos novos)."""
import subprocess
import sys
from pathlib import Path

from nomos.simple import erros

ROOT = Path(__file__).resolve().parent.parent


def _cli(args, home: Path, cwd=ROOT):
    return subprocess.run(
        [sys.executable, "-m", "nomos", *args],
        capture_output=True, text=True, timeout=90, cwd=str(cwd),
        env={"NOMOS_HOME": str(home), "PATH": ""},
    )


# ----------------------------------------------------------------- A6
def test_a6_codigos_novos_catalogados_e_documentados():
    for codigo in ("E011", "E012"):
        assert codigo in erros.CODIGOS and codigo in erros.HUMANO
        assert erros.explicar(codigo)
    doc = (ROOT / "docs" / "ERROS.md").read_text(encoding="utf-8")
    assert "NOMOS-E011" in doc and "NOMOS-E012" in doc


def test_a6_evidencia_violada_emite_e011(tmp_path):
    _cli(["evidencia", "criar", "m"], tmp_path)
    pacote = next((tmp_path / "evidencias").glob("EVIDENCIA_*"))
    (pacote / "manifest.json").write_text("{}", encoding="utf-8")
    proc = _cli(["evidencia", "verificar", str(pacote)], tmp_path)
    assert proc.returncode == 1
    assert "NOMOS-E011" in proc.stderr


def test_a6_nuvem_sem_terminal_emite_e012(tmp_path):
    proc = _cli(["motores", "arbitrar", "oi", "--nuvem"], tmp_path)
    assert proc.returncode == 3
    assert "NOMOS-E012" in proc.stderr and "decisão humana" in proc.stderr


# ----------------------------------------------------------------- A3
def test_a3_doutor_no_repo_mostra_guardioes(tmp_path):
    # MC36: o guardião virou OPT-IN (--repo) — rodar scripts do CWD sem
    # pedido explícito era exec fail-open (ver test_revisao_seguranca_2026)
    proc = _cli(["doutor", "--repo"], tmp_path, cwd=ROOT)
    assert proc.returncode == 0, proc.stderr
    assert "Guardião do repositório" in proc.stdout
    assert "docs & marca" in proc.stdout and "git:" in proc.stdout


def test_a3_doutor_no_repo_sem_flag_nao_executa(tmp_path):
    # sem --repo, mesmo DENTRO do repo: nada do CWD roda nem aparece
    proc = _cli(["doutor"], tmp_path, cwd=ROOT)
    assert proc.returncode == 0, proc.stderr
    assert "Guardião do repositório" not in proc.stdout


def test_a3_doutor_fora_do_repo_nao_mostra_secao(tmp_path):
    fora = tmp_path / "fora"
    fora.mkdir()
    proc = _cli(["doutor"], tmp_path, cwd=fora)
    assert proc.returncode == 0, proc.stderr
    assert "Guardião do repositório" not in proc.stdout
