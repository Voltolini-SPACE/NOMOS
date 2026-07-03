"""Qualidade — a CLI testada de verdade (main() direto, sem subprocesso)."""
import io

import pytest

from nomos import cli
from nomos.cognition import motores


@pytest.fixture(autouse=True)
def _iso(nomos_home, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))   # nunca interativo aqui
    motores.limpar_cache()
    yield


def run(*argv):
    return cli.main(list(argv))


def test_init_e_status(capsys):
    assert run("init") == 0
    assert run("status") == 0
    out = capsys.readouterr().out
    assert "NOMOS" in out and "fail-closed" in out


def test_agent_create_e_nome_invalido(capsys):
    run("init")
    assert run("agent", "create", "--name", "Atlas") == 0
    assert run("agent", "create", "--name", "1ruim!") == 1


def test_vault_fluxo_com_passphrase_por_env(monkeypatch, capsys):
    run("init")
    monkeypatch.setenv("NOMOS_PASSPHRASE", "frase-grande-demais-10")
    assert run("vault", "init") == 0
    monkeypatch.setattr("sys.stdin", io.StringIO("sk-VALOR-secreto-000\n"))
    assert run("vault", "set", "api") == 0
    assert run("vault", "list") == 0
    assert "api" in capsys.readouterr().out
    assert run("vault", "get", "api") == 3        # gate A3 nega fora de TTY


def test_run_nao_interativo_nega(capsys):
    run("init")
    assert run("run", "echo oi") == 3
    assert "fail-closed" in capsys.readouterr().err


def test_consent_grant_nega_fora_de_tty():
    run("init")
    assert run("consent", "grant", "microfone") == 3


def test_panic_e_logs_verify(capsys):
    run("init")
    assert run("panic") == 0
    assert run("logs", "verify") == 0
    assert "ÍNTEGRA" in capsys.readouterr().out


def test_memory_ciclo_completo(capsys):
    run("init")
    assert run("memory", "note", "pagar", "aluguel", "dia", "5") == 0
    assert run("memory", "search", "aluguel") == 0
    assert "aluguel" in capsys.readouterr().out
    assert run("memory", "recent") == 0
    assert run("memory", "stats") == 0
    assert "fts5" in capsys.readouterr().out
    assert run("memory", "forget", "1") == 0
    assert run("memory", "forget", "99") == 1


def test_motores_listar_e_usar(monkeypatch, capsys):
    run("init")
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: ["hermes3:8b"])
    assert run("motores") == 0
    assert "← ativo" in capsys.readouterr().out
    assert run("motores", "usar", "codigo", "texto") == 0
    assert run("motores", "usar", "video", "x") == 1


def test_chat_degradado_nao_interativo(capsys):
    run("init")
    rc = run("chat", "qual", "a", "capital?")
    assert rc == 1                                 # degradado honesto
    assert "MODO DEGRADADO" in capsys.readouterr().out


def test_chat_cloud_nao_interativo_nega(capsys):
    run("init")
    assert run("chat", "--cloud", "oi") == 3


def test_start_fora_de_tty_orienta_e_sai(capsys):
    assert run("start") == 1
    assert "terminal interativo" in capsys.readouterr().err


def test_skill_keygen_e_trust_revoke_desconhecido(capsys, tmp_path):
    run("init")
    assert run("skill", "keygen") == 0
    out = capsys.readouterr().out
    assert "pubkey" in out
    assert run("skill", "trust", "revoke", "deadbeef00000000") == 1


def test_skill_install_inexistente_falha_limpo(tmp_path):
    run("init")
    assert run("skill", "install", str(tmp_path / "nada")) == 3


def test_approvals_list_vazio(capsys):
    run("init")
    assert run("approvals", "list") == 0
    assert "nenhuma" in capsys.readouterr().out


def test_chaves_listar_vazio_sem_tty(capsys):
    run("init")
    assert run("chaves", "listar") == 0
    assert "nenhuma chave" in capsys.readouterr().out


def test_chaves_menu_exige_tty(capsys):
    run("init")
    assert run("chaves") == 1            # menu que pede senha nega fora de TTY
    assert "terminal interativo" in capsys.readouterr().err


def test_nomos_sem_comando_sem_tty_mostra_ajuda(capsys):
    assert run() == 0
    out = capsys.readouterr().out
    assert "start" in out and "chaves" in out


def test_erro_inesperado_vira_frase_amigavel(capsys, monkeypatch):
    run("init")
    def explode(ctx, args):
        raise RuntimeError("kaboom interno")
    monkeypatch.setattr("nomos.cli.cmd_status", explode)
    rc = run("status")
    err = capsys.readouterr().err
    assert rc == 1
    assert "Algo deu errado" in err and "kaboom" not in err.split("suporte")[0]
    assert "RuntimeError" in err            # detalhe técnico fica no rodapé


def test_local_status_padrao_ligado(capsys):
    run("init")
    assert run("local", "status") == 0
    assert "LIGADO" in capsys.readouterr().out


def test_local_off_exige_tty(capsys):
    run("init")
    assert run("local", "off") == 3        # decisão consciente exige terminal
    assert "consciente" in capsys.readouterr().err


def test_local_on_sempre_permitido(capsys):
    run("init")
    assert run("local", "on") == 0
    assert "LIGADO" in capsys.readouterr().out


def test_cerebro_status(capsys):
    run("init")
    assert run("cerebro", "status") == 0
    out = capsys.readouterr().out
    assert "RAM" in out and "recomendado" in out.lower()


def test_cerebro_baixar_nao_interativo_nega(capsys):
    run("init")
    assert run("cerebro", "baixar") == 3          # gate A2 nega fora de TTY
    assert "não autorizado" in capsys.readouterr().err


def test_tema_paleta_e_invalida(capsys):
    run("init")
    assert run("tema", "paleta", "floresta") == 0
    assert run("tema", "destaque", "turquesa") == 1


def test_local_status_e_toggle(capsys):
    run("init")
    assert run("local", "status") == 0
    assert "LIGADO" in capsys.readouterr().out
    assert run("local", "off") == 3                # decisão consciente exige TTY


def test_doutor_menciona_cerebro(capsys):
    run("init")
    assert run("doutor") == 0
    out = capsys.readouterr().out
    assert "Check-up" in out and "cérebro" in out.lower()


def test_motores_lista(capsys):
    run("init")
    assert run("motores") == 0
    assert "texto" in capsys.readouterr().out


def test_chaves_listar_vazio(capsys):
    run("init")
    assert run("chaves", "listar") == 0
    assert "nenhuma chave" in capsys.readouterr().out
