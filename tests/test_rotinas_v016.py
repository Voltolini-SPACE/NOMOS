"""v0.16 — rotinas locais: nascem com aprovação, rodam só o que é seguro."""
import hashlib
import io
import json
from datetime import datetime

import pytest

from nomos import cli
from nomos.ext import skill_registry as reg
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
            "audit": AuditLog(nomos_home / "logs" / "audit.jsonl"),
            "skills": nomos_home / "skills"}


# ---------------- criação governada ----------------

def test_criar_exige_aprovacao_humana(nomos_home):
    ctx = _ctx(nomos_home)
    with pytest.raises(rot.RotinaError, match="não aprovada"):
        rot.criar(nomos_home, "Briefing", "08:00", "briefing",
                  ctx["policy"], approver=None)
    assert rot.listar(nomos_home) == []
    nova = rot.criar(nomos_home, "Briefing", "08:00", "briefing",
                     ctx["policy"], approver=lambda d: True, audit=ctx["audit"])
    assert nova["id"] == 1 and rot.listar(nomos_home)[0]["nome"] == "Briefing"


def test_validacoes_de_hora_e_acao(nomos_home):
    ctx = _ctx(nomos_home)
    with pytest.raises(rot.RotinaError, match="hora inválida"):
        rot.criar(nomos_home, "x", "25:99", "briefing", ctx["policy"], lambda d: True)
    with pytest.raises(rot.RotinaError, match="ação desconhecida"):
        rot.criar(nomos_home, "x", "08:00", "rm -rf /", ctx["policy"], lambda d: True)
    with pytest.raises(rot.RotinaError, match="não está instalada"):
        rot.criar(nomos_home, "x", "08:00", "skill:fantasma", ctx["policy"],
                  lambda d: True, skills_dir=ctx["skills"])


# ---------------- agenda ----------------

def test_devidas_por_horario_e_uma_vez_por_dia(nomos_home):
    ctx = _ctx(nomos_home)
    rot.criar(nomos_home, "Manhã", "08:00", "briefing", ctx["policy"], lambda d: True)
    rot.criar(nomos_home, "Noite", "22:00", "doutor", ctx["policy"], lambda d: True)
    meio_dia = datetime(2026, 7, 3, 12, 0)
    nomes = [r["nome"] for r in rot.devidas(nomos_home, meio_dia)]
    assert nomes == ["Manhã"]                      # 22:00 ainda não chegou
    ctx2 = _ctx(nomos_home)
    resultados = rot.executar_devidas(ctx2, meio_dia, say=lambda *_: None)
    assert [r["ok"] for r in resultados] == [True]
    assert rot.devidas(nomos_home, meio_dia) == [] # não roda 2x no mesmo dia


def test_rotina_pausada_nao_roda(nomos_home):
    ctx = _ctx(nomos_home)
    nova = rot.criar(nomos_home, "Manhã", "08:00", "briefing",
                     ctx["policy"], lambda d: True)
    rot.pausar(nomos_home, nova["id"], False)
    assert rot.devidas(nomos_home, datetime(2026, 7, 3, 12, 0)) == []


# ---------------- execução segura ----------------

def test_skill_sensivel_nao_roda_em_rotina(tmp_path, nomos_home):
    """Rotina roda sem humano => skill que pede aprovação é negada (design)."""
    ctx = _ctx(nomos_home)
    corpo = 'print("nao deveria rodar")\n'
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text(corpo, encoding="utf-8", newline="\n")
    (src / "skill.json").write_text(json.dumps({
        "name": "gravadora", "version": "1.0.0", "entry": "main.py",
        "permissions": ["A1_WRITE_LOCAL"],
        "files": {"main.py": hashlib.sha256(corpo.encode()).hexdigest()}}))
    reg.instalar(src, ctx["skills"], ctx["policy"], lambda d: True,
                 confirmar_experimental=lambda m: True)
    ok, detalhe = rot.executar_acao(ctx, "skill:gravadora", say=lambda *_: None)
    assert ok is False and "não rodam sozinhas" in detalhe


def test_briefing_junta_tarefas_e_proximo_passo(nomos_home, monkeypatch):
    from nomos.cognition import motores
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: [])
    monkeypatch.setattr(motores, "_http_ok", lambda *a, **k: False)
    monkeypatch.setattr("shutil.which", lambda *a, **k: None)
    motores.limpar_cache()
    ctx = _ctx(nomos_home)
    from nomos.cognition.memory import Memory
    Memory(nomos_home / "memory.db").remember("note", "tarefa: renovar passaporte")
    texto = rot.briefing(ctx)
    assert "renovar passaporte" in texto
    assert "próximo passo" in texto
    assert "nada saiu dela" in texto
    motores.limpar_cache()


def test_arquivo_de_rotinas_corrompido_nada_roda(nomos_home):
    nomos_home.mkdir(parents=True, exist_ok=True)
    (nomos_home / "rotinas.json").write_text("{quebrado")
    assert rot.listar(nomos_home) == []
    assert rot.devidas(nomos_home) == []


# ---------------- CLI ----------------

def test_cli_criar_nega_sem_tty_e_listar(nomos_home, capsys):
    assert cli.main(["init"]) == 0
    rc = cli.main(["rotinas", "criar", "Briefing", "08:00", "briefing"])
    assert rc == 3                                  # gate A1 sem TTY nega
    assert cli.main(["rotinas"]) == 0
    assert "nenhuma rotina" in capsys.readouterr().out


def test_cli_executar_e_agendar(nomos_home, capsys):
    assert cli.main(["init"]) == 0
    assert cli.main(["rotinas", "executar"]) == 0
    assert "tudo em dia" in capsys.readouterr().out
    assert cli.main(["rotinas", "agendar"]) == 0
    out = capsys.readouterr().out
    assert "crontab" in out and "nunca altera seu agendador" in out
