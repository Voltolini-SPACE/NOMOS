"""MC32/P1 — Executor de missões: plano → aprovação explícita → evidência → desfazer."""
import subprocess
import sys
from pathlib import Path

import pytest

from nomos.kernel import evidencia as ev
from nomos.kernel import missao as ms
from _cli_env import cli_env

ROOT = Path(__file__).resolve().parent.parent


def _pasta_baguncada(tmp_path: Path) -> Path:
    d = tmp_path / "downloads"
    d.mkdir()
    for nome in ("contrato.pdf", "foto.png", "musica.mp3", "dados.csv",
                 "slide.pptx", "coisa.xyz", ".oculto"):
        (d / nome).write_text("x", encoding="utf-8")
    (d / "subpasta").mkdir()
    (d / "subpasta" / "dentro.txt").write_text("x", encoding="utf-8")
    return d


def _cli(args, home: Path):
    return subprocess.run(
        [sys.executable, "-m", "nomos", *args],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT),
        env=cli_env(home),
    )


# 1. planejar: determinístico, categoriza e NÃO toca o disco
def test_planejar_categoriza_sem_tocar_o_disco(tmp_path):
    d = _pasta_baguncada(tmp_path)
    antes = sorted(p.name for p in d.rglob("*"))
    plano = ms.planejar_organizacao(d)
    assert sorted(p.name for p in d.rglob("*")) == antes
    destinos = {p.origem: p.destino for p in plano.passos}
    assert destinos["contrato.pdf"] == "documentos/contrato.pdf"
    assert destinos["foto.png"] == "imagens/foto.png"
    assert destinos["coisa.xyz"] == "outros/coisa.xyz"
    assert ".oculto" not in destinos and "subpasta" not in destinos
    assert plano.executavel and all(p.nivel == "A1" for p in plano.passos)


# 2. colisão de destino invalida o plano (nunca sobrescreve)
def test_colisao_invalida_o_plano(tmp_path):
    d = _pasta_baguncada(tmp_path)
    (d / "documentos").mkdir()
    (d / "documentos" / "contrato.pdf").write_text("JÁ EXISTO", encoding="utf-8")
    plano = ms.planejar_organizacao(d)
    assert not plano.executavel
    assert "documentos/contrato.pdf" in plano.conflitos


# 3. executar sem aprovação: fail-closed no módulo
def test_executar_sem_aprovacao_recusa(tmp_path):
    d = _pasta_baguncada(tmp_path)
    plano = ms.planejar_organizacao(d)
    with pytest.raises(ms.MissaoErro, match="aprovação"):
        ms.executar(plano, aprovado=False, evidencias_dir=tmp_path / "e")
    assert (d / "contrato.pdf").exists()


# 4. execução aprovada: move tudo, evidência verificável com DESFAZER
def test_executar_move_e_gera_evidencia_verificavel(tmp_path):
    d = _pasta_baguncada(tmp_path)
    plano = ms.planejar_organizacao(d)
    pacote = ms.executar(plano, aprovado=True, evidencias_dir=tmp_path / "e")
    assert (d / "documentos" / "contrato.pdf").exists()
    assert (d / "imagens" / "foto.png").exists()
    assert not (d / "contrato.pdf").exists()
    assert (d / "subpasta" / "dentro.txt").exists()      # intocada
    ok, problemas = ev.verificar_pacote(pacote)
    assert ok, problemas                                  # DESFAZER no SHA256SUMS
    assert (pacote / ms.DESFAZER_ARQ).is_file()


# 5. desfazer: tudo de volta, também gateado
def test_desfazer_reverte_tudo(tmp_path):
    d = _pasta_baguncada(tmp_path)
    plano = ms.planejar_organizacao(d)
    pacote = ms.executar(plano, aprovado=True, evidencias_dir=tmp_path / "e")
    with pytest.raises(ms.MissaoErro):
        ms.desfazer(pacote, d, aprovado=False)
    n = ms.desfazer(pacote, d, aprovado=True)
    assert n == len(plano.passos)
    assert (d / "contrato.pdf").exists()
    assert not (d / "documentos" / "contrato.pdf").exists()


# 6. CLI: planejar é dry-run; executar sem TTY nega com E002 e nada se move
def test_cli_planejar_dry_run(tmp_path):
    d = _pasta_baguncada(tmp_path)
    proc = _cli(["missao", "planejar", "organizar", str(d)], tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "nada foi movido" in proc.stdout
    assert (d / "contrato.pdf").exists()


def test_cli_executar_sem_tty_nega(tmp_path):
    d = _pasta_baguncada(tmp_path)
    proc = _cli(["missao", "executar", "organizar", str(d)], tmp_path)
    assert proc.returncode == 3
    assert "NOMOS-E002" in proc.stderr
    assert (d / "contrato.pdf").exists(), "nada pode mover sem aprovação"


def test_cli_pasta_inexistente_e003(tmp_path):
    proc = _cli(["missao", "planejar", "organizar", str(tmp_path / "nao")],
                tmp_path)
    assert proc.returncode == 1 and "NOMOS-E003" in proc.stderr


# ---------------------------------------------------------------- P2: renomear
def test_p2_renomear_plano_mostra_diff_e_nao_toca(tmp_path):
    d = tmp_path / "docs"
    d.mkdir()
    for nome in ("relatorio final v1.txt", "relatorio final v2.txt", "outro.md"):
        (d / nome).write_text("x", encoding="utf-8")
    plano = ms.planejar_renomeacao(d, " final ", "-")
    assert plano.executavel and len(plano.passos) == 2
    assert plano.passos[0].destino == "relatorio-v1.txt"
    assert "relatorio final v1.txt  →  relatorio-v1.txt" in plano.resumo()
    assert (d / "relatorio final v1.txt").exists()      # dry-run de verdade


def test_p2_renomear_colisao_invalida(tmp_path):
    d = tmp_path / "docs"
    d.mkdir()
    (d / "a_x.txt").write_text("1", encoding="utf-8")
    (d / "a_y.txt").write_text("2", encoding="utf-8")
    plano = ms.planejar_renomeacao(d, "_x", "_z")
    assert plano.executavel                               # sem colisão: ok
    plano2 = ms.planejar_renomeacao(d, "x", "y")          # a_x→a_y JÁ existe
    assert not plano2.executavel and plano2.conflitos


def test_p2_renomear_executa_e_desfaz(tmp_path):
    d = tmp_path / "docs"
    d.mkdir()
    (d / "IMG 001.png").write_text("x", encoding="utf-8")
    (d / "IMG 002.png").write_text("x", encoding="utf-8")
    plano = ms.planejar_renomeacao(d, "IMG ", "ferias-")
    pacote = ms.executar(plano, aprovado=True, evidencias_dir=tmp_path / "e")
    assert (d / "ferias-001.png").exists() and not (d / "IMG 001.png").exists()
    assert ms.desfazer(pacote, d, aprovado=True) == 2
    assert (d / "IMG 001.png").exists()


def test_p2_cli_renomear_sem_de_e010(tmp_path):
    d = tmp_path / "docs"
    d.mkdir()
    proc = _cli(["missao", "planejar", "renomear", str(d)], tmp_path)
    assert proc.returncode == 1 and "NOMOS-E010" in proc.stderr


def test_p2_cli_renomear_executar_sem_tty_nega(tmp_path):
    d = tmp_path / "docs"
    d.mkdir()
    (d / "IMG 1.png").write_text("x", encoding="utf-8")
    proc = _cli(["missao", "executar", "renomear", str(d),
                 "--de", "IMG ", "--para", "f-"], tmp_path)
    assert proc.returncode == 3 and "NOMOS-E002" in proc.stderr
    assert (d / "IMG 1.png").exists()
