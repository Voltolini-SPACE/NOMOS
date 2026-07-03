"""Fase 3/6 — UX de motores na CLI: listar, recomendar, auto, testar, menu."""
import io

import pytest

from nomos import cli
from nomos.cognition import engine_policy as epol
from nomos.cognition import motores


@pytest.fixture(autouse=True)
def _iso(nomos_home, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))   # nunca interativo
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: [])
    monkeypatch.setattr(motores, "_http_ok", lambda *a, **k: False)
    monkeypatch.setattr("shutil.which", lambda *a, **k: None)
    motores.limpar_cache()
    yield
    motores.limpar_cache()


def run(*argv):
    return cli.main(list(argv))


def _com_ollama(monkeypatch):
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: ["hermes3:8b"])
    motores.limpar_cache()


def test_compat_motores_sem_subcomando(capsys):
    run("init")
    assert run("motores") == 0
    assert "texto" in capsys.readouterr().out   # tabela clássica preservada


def test_motores_listar_v011(capsys):
    run("init")
    assert run("motores", "listar") == 0
    out = capsys.readouterr().out
    for trecho in ("privacidade", "qualidade", "roteador automático"):
        assert trecho in out


def test_motores_status_igual_listar(capsys):
    run("init")
    assert run("motores", "status") == 0
    assert "Motores do NOMOS" in capsys.readouterr().out


def test_recomendar_com_motor_local(monkeypatch, capsys):
    run("init")
    _com_ollama(monkeypatch)
    assert run("motores", "recomendar", "texto") == 0
    out = capsys.readouterr().out
    assert "recomendado para texto: ollama" in out
    assert "privacidade" in out


def test_recomendar_sem_motor_orienta_proximo_passo(capsys):
    run("init")
    assert run("motores", "recomendar", "texto") == 1
    saida = capsys.readouterr()
    assert "nenhum motor pronto" in saida.out
    assert "Próximo passo" in saida.out


def test_recomendar_modalidade_invalida(capsys):
    run("init")
    assert run("motores", "recomendar", "telepatia") == 1
    assert "modalidade desconhecida" in capsys.readouterr().err


def test_auto_on_off(capsys):
    run("init")
    assert run("motores", "auto", "off") == 0
    assert epol.auto_ligado() is False
    assert run("motores", "auto", "on") == 0
    assert epol.auto_ligado() is True
    assert "LIGADO" in capsys.readouterr().out


def test_testar_motor(capsys):
    run("init")
    assert run("motores", "testar", "memoria-local") == 0
    assert "PRONTO" in capsys.readouterr().out
    assert run("motores", "testar", "ollama") == 1
    assert run("motores", "testar", "inexistente") == 1


def test_diagnostico(capsys):
    run("init")
    assert run("motores", "diagnostico") == 0
    out = capsys.readouterr().out
    assert "modalidades prontas" in out and "memoria" in out
    assert "só-local" in out


def test_menu_sem_tty_cai_para_tabela(capsys):
    run("init")
    assert run("motores", "menu") == 0
    assert "Motores do NOMOS" in capsys.readouterr().out


def test_menu_interativo_injetado(monkeypatch, capsys, nomos_home):
    run("init")
    respostas = iter(["1", "4", "5"])
    ditos = []
    rc = cli._motores_menu({"home": nomos_home},
                           ask=lambda p: next(respostas), say=ditos.append)
    assert rc == 0
    assert any("Motores do NOMOS" in str(d) for d in ditos)


def test_usar_continua_funcionando(monkeypatch, capsys):
    run("init")
    _com_ollama(monkeypatch)
    assert run("motores", "usar", "codigo", "texto") == 0
    assert run("motores", "usar", "video", "x") == 1


def test_status_sobrevive_a_perfil_parcial(monkeypatch, capsys):
    """Regressão: 'motores usar'/'auto' antes do onboarding cria perfil sem
    agent_name — 'nomos status' não pode quebrar por isso."""
    run("init")
    _com_ollama(monkeypatch)
    assert run("motores", "usar", "codigo", "texto") == 0   # perfil parcial
    assert run("status") == 0
    assert "crie com nomos agent create" in capsys.readouterr().out
    assert run("motores", "auto", "off") == 0               # também parcial
    assert run("status") == 0
