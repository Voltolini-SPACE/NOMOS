"""MC29 — Sistema de Evidências: pacote auditável, redigido e verificável offline."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from nomos.kernel import evidencia as ev

ROOT = Path(__file__).resolve().parent.parent


def _pacote_basico(tmp_path, monkeypatch=None, titulo="Missão X"):
    anexo = tmp_path / "log.txt"
    anexo.write_text("linha de log\n", encoding="utf-8")
    return ev.gerar_pacote(
        tmp_path / "evidencias", titulo, status="PASS",
        comandos=[{"comando": "pytest -q", "retorno": 0, "resultado": "1139 passed"}],
        anexos=[anexo], notas="nota da missão")


# 1. roundtrip: gerar → estrutura completa → verificar OK
def test_gerar_e_verificar_roundtrip(tmp_path):
    pacote = _pacote_basico(tmp_path)
    for rel in ("RELATORIO.md", "manifest.json", "SHA256SUMS", "anexos/log.txt"):
        assert (pacote / rel).is_file(), f"faltou {rel}"
    ok, problemas = ev.verificar_pacote(pacote)
    assert ok, problemas
    manifesto = json.loads((pacote / "manifest.json").read_text(encoding="utf-8"))
    assert manifesto["formato"] == ev.PACOTE_VERSAO
    assert manifesto["redigido"] is True
    assert manifesto["comandos"][0]["retorno"] == 0


# 2. segredos nunca tocam o disco (redação herdada do kernel.audit)
def test_segredo_e_redigido_no_pacote(tmp_path):
    chave_falsa = "sk-" + "A" * 30
    pacote = ev.gerar_pacote(
        tmp_path / "evidencias", "vazamento?", status="PASS",
        comandos=[{"comando": f"export KEY={chave_falsa}", "retorno": 0,
                   "resultado": chave_falsa}],
        notas=f"nota com {chave_falsa}")
    for rel in ("RELATORIO.md", "manifest.json"):
        conteudo = (pacote / rel).read_text(encoding="utf-8")
        assert chave_falsa not in conteudo, f"segredo vazou em {rel}"


# 3. fail-closed: anexo ausente e pacote duplicado
def test_anexo_ausente_falha_fechado(tmp_path):
    with pytest.raises(FileNotFoundError):
        ev.gerar_pacote(tmp_path / "e", "t", status="PASS",
                        anexos=[tmp_path / "nao_existe.txt"])
    assert not (tmp_path / "e").exists(), "não pode deixar pacote meio-escrito"


def test_pacote_duplicado_nao_sobrescreve(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "_agora_utc", lambda: "20260705T000000Z")
    ev.gerar_pacote(tmp_path / "e", "mesmo título", status="PASS")
    with pytest.raises(FileExistsError):
        ev.gerar_pacote(tmp_path / "e", "mesmo título", status="PASS")


# 4. adulteração é detectada offline
def test_adulteracao_de_anexo_e_detectada(tmp_path):
    pacote = _pacote_basico(tmp_path)
    (pacote / "anexos" / "log.txt").write_text("ADULTERADO", encoding="utf-8")
    ok, problemas = ev.verificar_pacote(pacote)
    assert ok is False
    assert any("log.txt" in p for p in problemas)


def test_relatorio_adulterado_e_detectado(tmp_path):
    pacote = _pacote_basico(tmp_path)
    (pacote / "RELATORIO.md").write_text("# outro\n", encoding="utf-8")
    ok, problemas = ev.verificar_pacote(pacote)
    assert ok is False and any("RELATORIO.md" in p for p in problemas)


# 5. CLI real: criar e verificar com exit codes honestos
def _cli(args, home: Path):
    return subprocess.run(
        [sys.executable, "-m", "nomos", *args],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT),
        env={"NOMOS_HOME": str(home), "PATH": ""},
    )


def test_cli_evidencia_criar_e_verificar(tmp_path):
    proc = _cli(["evidencia", "criar", "missão de teste", "--nota", "ok"], tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "pacote de evidências criado" in proc.stdout
    assert "OK ✓" in proc.stdout
    pacotes = list((tmp_path / "evidencias").glob("EVIDENCIA_*"))
    assert len(pacotes) == 1
    proc2 = _cli(["evidencia", "verificar", str(pacotes[0])], tmp_path)
    assert proc2.returncode == 0 and "íntegro" in proc2.stdout


def test_cli_evidencia_verificar_detecta_adulteracao(tmp_path):
    _cli(["evidencia", "criar", "m"], tmp_path)
    pacote = next((tmp_path / "evidencias").glob("EVIDENCIA_*"))
    (pacote / "manifest.json").write_text("{}", encoding="utf-8")
    proc = _cli(["evidencia", "verificar", str(pacote)], tmp_path)
    assert proc.returncode == 1
    assert "NÃO confere" in proc.stderr


def test_cli_evidencia_sem_subcomando_orienta_e_sai_erro(tmp_path):
    proc = _cli(["evidencia"], tmp_path)
    assert proc.returncode == 1
    assert "uso:" in proc.stderr
