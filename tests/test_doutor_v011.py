"""Fase 7 — doutor v0.11: STATUS GERAL + próximo passo acionável."""
import io

import pytest

from nomos import cli
from nomos.cognition import motores
from nomos.kernel import config
from nomos.kernel.audit import AuditLog
from nomos.simple import doutor


@pytest.fixture(autouse=True)
def _iso(nomos_home, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: [])
    monkeypatch.setattr(motores, "_http_ok", lambda *a, **k: False)
    monkeypatch.setattr("shutil.which", lambda *a, **k: None)
    motores.limpar_cache()
    yield
    motores.limpar_cache()


def test_status_geral_parcial_sem_cerebro(nomos_home):
    config.ensure_home()
    itens = doutor.diagnostico_v011(nomos_home)
    assert doutor.status_geral(itens) == "PARCIAL"
    rel = doutor.texto_relatorio_v011(nomos_home)
    assert "STATUS GERAL: PARCIAL" in rel
    assert "Próximo passo recomendado:" in rel


def test_proximo_passo_prioriza_bloqueante():
    itens = [
        {"ok": False, "titulo": "a", "detalhe": "", "proximo": "passo-opcional",
         "bloqueante": False},
        {"ok": False, "titulo": "b", "detalhe": "", "proximo": "passo-urgente",
         "bloqueante": True},
    ]
    assert doutor.proximo_passo(itens) == "passo-urgente"
    assert doutor.status_geral(itens) == "BLOQUEADO"


def test_tudo_ok_fica_pronto():
    itens = [{"ok": True, "titulo": "x", "detalhe": "", "proximo": "",
              "bloqueante": False}]
    assert doutor.status_geral(itens) == "PRONTO"
    assert "nada pendente" in doutor.proximo_passo(itens)


def test_auditoria_violada_bloqueia(nomos_home):
    config.ensure_home()
    log = AuditLog(nomos_home / "logs" / "audit.jsonl")
    log.append("evento.um", x=1)
    log.append("evento.dois", x=2)
    caminho = nomos_home / "logs" / "audit.jsonl"
    adulterado = caminho.read_text().replace('"x":1', '"x":999')
    caminho.write_text(adulterado)
    itens = doutor.diagnostico_v011(nomos_home)
    assert doutor.status_geral(itens) == "BLOQUEADO"
    assert "VIOLADA" in doutor.texto_relatorio_v011(nomos_home)


def test_skill_quebrada_aparece_no_checkup(nomos_home):
    config.ensure_home()
    dest = nomos_home / "skills" / "zumbi"
    dest.mkdir(parents=True)
    (dest / "skill.json").write_text("{não é json")
    rel = doutor.texto_relatorio_v011(nomos_home)
    assert "Skill quebrada: zumbi" in rel


def test_cli_doutor_usa_v011(capsys):
    assert cli.main(["init"]) == 0
    assert cli.main(["doutor"]) == 0
    out = capsys.readouterr().out
    assert "Check-up" in out                 # compat com expectativa antiga
    assert "STATUS GERAL:" in out
    assert "Próximo passo recomendado:" in out
    assert "cérebro" in out.lower()


def test_diagnostico_v010_continua_estavel(nomos_home):
    """A função antiga não muda de formato (compat)."""
    config.ensure_home()
    assert all(set(i) == {"ok", "titulo", "detalhe"}
               for i in doutor.diagnostico())
