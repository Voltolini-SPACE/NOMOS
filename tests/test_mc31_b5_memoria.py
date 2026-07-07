"""MC31/B5 — Memória 2.0: revisão humana da fila de candidatas (CLI + painel)."""
import io
import json
import subprocess
import sys
from pathlib import Path

from nomos.cognition.memory import Memory
from _cli_env import cli_env

ROOT = Path(__file__).resolve().parent.parent


def _cli(args, home: Path):
    return subprocess.run(
        [sys.executable, "-m", "nomos", *args],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT),
        env=cli_env(home),
    )


def _semear(home: Path) -> Memory:
    mem = Memory(home / "memory.db")
    mem.propor_candidata("usuário prefere respostas curtas")
    mem.propor_candidata("aniversário do sócio é 1º de maio")
    return mem


# 1. candidatas: lista e --json estável
def test_cli_candidatas_lista_e_json(tmp_path):
    _semear(tmp_path)
    proc = _cli(["memoria", "candidatas"], tmp_path)
    assert proc.returncode == 0
    assert "aguardando SUA revisão (2)" in proc.stdout
    data = json.loads(_cli(["memoria", "candidatas", "--json"], tmp_path).stdout)
    assert data["contrato"] == 1 and len(data["candidatas"]) == 2


def test_cli_candidatas_vazia_tranquiliza(tmp_path):
    proc = _cli(["memoria", "candidatas"], tmp_path)
    assert proc.returncode == 0 and "memória em dia" in proc.stdout


# 2. revisar sem TTY: fail-closed — NADA aprovado, fila intacta
def test_cli_revisar_sem_tty_nao_aprova_nada(tmp_path):
    mem = _semear(tmp_path)
    proc = _cli(["memoria", "revisar"], tmp_path)
    assert proc.returncode == 3
    assert "NOMOS-E002" in proc.stderr
    assert len(mem.candidatas()) == 2, "fila deveria seguir intacta"
    assert mem.count() == 0, "nada pode virar memória sem aprovação humana"


# 3. revisão interativa (em processo, com stdin/stdout fakes de TTY)
def test_revisar_interativo_aprova_e_descarta(tmp_path, monkeypatch, capsys):
    from nomos import cli as cli_mod
    _semear(tmp_path)
    monkeypatch.setenv("NOMOS_HOME", str(tmp_path))
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    respostas = iter(["s", "n"])
    monkeypatch.setattr("builtins.input", lambda *_: next(respostas))
    rc = cli_mod.main(["memoria", "revisar"])
    assert rc == 0
    saida = capsys.readouterr().out
    assert "1 aprovada(s), 1 descartada(s)" in saida
    mem = Memory(tmp_path / "memory.db")
    assert mem.count() == 1 and mem.candidatas() == []


# 4. painel mostra a fila e orienta o comando
def test_painel_mostra_fila_de_candidatas(nomos_home):
    from nomos.cognition import motores
    from nomos.interface.painel_web import dados_dashboard, render_html
    from nomos.kernel.audit import AuditLog
    from nomos.kernel.policy import PolicyEngine
    _semear(nomos_home)
    ctx = {"home": nomos_home,
           "policy": PolicyEngine(nomos_home / "policy.json"),
           "audit": AuditLog(nomos_home / "logs" / "audit.jsonl"),
           "skills": nomos_home / "skills"}
    motores.limpar_cache()
    corpo = render_html(dados_dashboard(ctx))
    assert "Memória local" in corpo
    assert "2</b> candidata(s)" in corpo
    assert "nomos memoria revisar" in corpo
