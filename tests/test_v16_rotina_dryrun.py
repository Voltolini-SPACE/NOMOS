"""F5 — rotina dry-run: simular mostra o que faria, sem efeito."""
import io
from datetime import datetime

import pytest

from nomos import cli
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import PolicyEngine
from nomos.simple import rotinas as rot


@pytest.fixture(autouse=True)
def _iso(nomos_home, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    yield


def _ctx(nomos_home):
    nomos_home.mkdir(parents=True, exist_ok=True)
    (nomos_home / "skills").mkdir(exist_ok=True)
    return {"home": nomos_home,
            "policy": PolicyEngine(nomos_home / "policy.json"),
            "audit": AuditLog(nomos_home / "logs" / "a.jsonl"),
            "skills": nomos_home / "skills"}


def test_prever_descreve_sem_executar():
    assert "briefing do dia" in rot.prever_acao("briefing")
    assert "check-up" in rot.prever_acao("doutor")
    assert "só se ela for A0" in rot.prever_acao("skill:x")


def test_simular_nao_executa_nem_marca(nomos_home, monkeypatch):
    ctx = _ctx(nomos_home)
    rot.criar(nomos_home, "Manhã", "08:00", "consolidar-memoria",
              ctx["policy"], approver=lambda d: True)
    # se executasse de verdade, consolidar rodaria; garantimos que NÃO roda
    from nomos.cognition import memory as _mem
    monkeypatch.setattr(_mem.Memory, "consolidar",
                        lambda self: (_ for _ in ()).throw(
                            AssertionError("não deveria executar em simulação")))
    meio_dia = datetime(2026, 7, 3, 12, 0)
    resultados = rot.executar_devidas(ctx, meio_dia, say=lambda *_: None,
                                      simular=True)
    assert resultados and resultados[0]["ok"] is True
    assert "simulado" in resultados[0]["detalhe"]
    # não marcou como executada: continua devida
    assert rot.devidas(nomos_home, meio_dia)                # ainda pendente
    log = (nomos_home / "logs" / "a.jsonl").read_text()
    assert "rotina.simulada" in log and "rotina.executada" not in log


def test_execucao_real_depois_da_simulacao(nomos_home):
    ctx = _ctx(nomos_home)
    rot.criar(nomos_home, "Manhã", "08:00", "briefing",
              ctx["policy"], approver=lambda d: True)
    meio_dia = datetime(2026, 7, 3, 12, 0)
    rot.executar_devidas(ctx, meio_dia, say=lambda *_: None, simular=True)
    # simulação não consumiu a rotina; agora executa de verdade
    reais = rot.executar_devidas(ctx, meio_dia, say=lambda *_: None)
    assert reais and reais[0]["ok"] is True
    assert rot.devidas(nomos_home, meio_dia) == []          # agora consumida


def test_cli_rotinas_executar_simular(nomos_home, capsys):
    assert cli.main(["init"]) == 0
    assert cli.main(["rotinas", "executar", "--simular"]) == 0
    assert "tudo em dia" in capsys.readouterr().out
