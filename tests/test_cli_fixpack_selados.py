"""FIX-03 — `--executavel` nega na PORTA, com a verdade do selamento.

Antes, a flag era aceita, o runtime era construído e só então o usuário
recebia um `ErroRuntime` tardio, vestido de defeito interno. Agora
`nomos orquestrar` e `nomos scheduler` negam imediatamente (EXIT_DENIED),
sem construir runtime nenhum — e o texto de ajuda diz a mesma coisa.
"""
from __future__ import annotations

import pytest

from nomos import cli


@pytest.fixture()
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("NOMOS_HOME", str(h))
    return h


def test_orquestrar_executavel_nega_na_porta(home, tmp_path, capsys):
    rc = cli.main(["orquestrar", "objetivo qualquer",
                   "--adapters", "--raiz", str(tmp_path),
                   "--executavel", "/bin/ls"])
    err = capsys.readouterr().err
    assert rc == cli.EXIT_DENIED
    assert "SELADO" in err
    assert "script-rodar" in err


def test_orquestrar_executavel_nega_mesmo_sem_adapters(home, capsys):
    # A negação vem ANTES de qualquer outra validação de combinação de flags:
    # o selamento é a primeira verdade, não a última.
    rc = cli.main(["orquestrar", "objetivo", "--executavel", "/bin/ls"])
    err = capsys.readouterr().err
    assert rc == cli.EXIT_DENIED
    assert "SELADO" in err


def test_scheduler_executavel_nega_na_porta(home, tmp_path, capsys):
    rc = cli.main(["scheduler", "listar", "--raiz", str(tmp_path),
                   "--executavel", "/bin/ls"])
    err = capsys.readouterr().err
    assert rc == cli.EXIT_DENIED
    assert "SELADO" in err


def test_scheduler_sem_executavel_nao_cai_na_porta_nova(home, tmp_path, capsys):
    # Regressão: a porta nova não pode barrar quem NÃO usa a flag. O comando
    # ainda pode falhar por OUTRAS razões legítimas (ex.: aprovação exige
    # terminal interativo) — o que este teste fixa é que o selamento não
    # intercepta o caminho sem `--executavel`.
    rc = cli.main(["scheduler", "listar", "--raiz", str(tmp_path)])
    err = capsys.readouterr().err
    assert rc != cli.EXIT_DENIED
    assert "SELADO" not in err
