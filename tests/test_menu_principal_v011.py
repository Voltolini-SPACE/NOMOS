"""Fase 6 — `nomos` abre fluxo simples: menu principal amigável."""
import io

from nomos import cli
from nomos.kernel import localidade
from nomos.simple.menu_principal import cabecalho, menu_principal


def test_cabecalho_diz_que_esta_local(nomos_home):
    txt = cabecalho({"agent_name": "Atlas"}, nomos_home)
    assert "Atlas" in txt and "100% local" in txt


def test_cabecalho_avisa_nuvem_plugada(nomos_home):
    localidade.definir(nomos_home, False)
    assert "permissão" in cabecalho({}, nomos_home)


def test_menu_navega_e_sai(nomos_home):
    ditos, chamadas = [], []
    acoes = {"2": lambda: chamadas.append("status") or 0,
             "8": lambda: chamadas.append("doutor") or 0}
    respostas = iter(["2", "8", "99", "10"])
    rc = menu_principal({"home": nomos_home}, {"agent_name": "Atlas"}, acoes,
                        ask=lambda p: next(respostas), say=ditos.append)
    assert rc == 0
    assert chamadas == ["status", "doutor"]
    tudo = "\n".join(str(d) for d in ditos)
    assert "1. Conversar com meu agente" in tudo
    assert "opção desconhecida" in tudo          # o 99 não derruba o menu
    assert "até logo" in tudo


def test_menu_nao_derruba_com_erro_de_acao(nomos_home):
    ditos = []
    acoes = {"2": lambda: (_ for _ in ()).throw(RuntimeError("boom"))}
    respostas = iter(["2", "10"])
    rc = menu_principal({"home": nomos_home}, {}, acoes,
                        ask=lambda p: next(respostas), say=ditos.append)
    assert rc == 0
    tudo = "\n".join(str(d) for d in ditos)
    assert "nada foi perdido" in tudo and "boom" not in tudo   # sem traceback


def test_nomos_sem_tty_mostra_ajuda(nomos_home, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert cli.main([]) == 0
    assert "usage" in capsys.readouterr().out.lower()
