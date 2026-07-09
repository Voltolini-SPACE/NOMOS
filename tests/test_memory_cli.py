"""MC28 — NOMOS Memory Engine: interface de linha de comando (cli).

Cobre os contratos de saída da CLI: dry-run não grava e sai 0, apply grava,
segredo é recusado (saída 3), listagem, validação, falha-fechada em uso inválido
(saída 2) e campo inválido (saída 5), compact/report e saída JSON.
"""
import json

import pytest

from nomos.memory.cli import main


def test_cli_add_dry_run_nao_grava(tmp_path):
    d = tmp_path / "mem"
    rc = main(["--add", "memoria limpa via cli", "--base-dir", str(d)])
    assert rc == 0
    assert not d.exists()


def test_cli_add_apply_grava(tmp_path):
    d = tmp_path / "mem"
    rc = main(["--add", "memoria limpa via cli", "--apply", "--base-dir", str(d)])
    assert rc == 0
    assert (d / "memory.jsonl").exists()


def test_cli_segredo_recusado_saida_3(tmp_path):
    d = tmp_path / "mem"
    rc = main(["--add", "sk-ABCDEFGHIJKLMNOP1234567890xyz", "--apply", "--base-dir", str(d)])
    assert rc == 3
    assert not (d / "memory.jsonl").exists()


def test_cli_listagem(tmp_path, capsys):
    d = tmp_path / "mem"
    main(["--add", "achado importante do dia", "--apply", "--base-dir", str(d)])
    capsys.readouterr()
    rc = main(["--list", "--base-dir", str(d)])
    assert rc == 0
    assert "achado importante do dia" in capsys.readouterr().out


def test_cli_validate_ok(tmp_path):
    d = tmp_path / "mem"
    main(["--add", "conteudo ok", "--apply", "--base-dir", str(d)])
    assert main(["--validate", "--base-dir", str(d)]) == 0


def test_cli_sem_acao_falha_fechado(tmp_path):
    with pytest.raises(SystemExit) as ei:
        main(["--base-dir", str(tmp_path / "mem")])
    assert ei.value.code == 2


def test_cli_apply_e_dryrun_conflito(tmp_path):
    with pytest.raises(SystemExit) as ei:
        main(["--add", "x", "--apply", "--dry-run", "--base-dir", str(tmp_path / "mem")])
    assert ei.value.code == 2


def test_cli_campo_invalido_saida_5(tmp_path):
    d = tmp_path / "mem"
    assert main(["--add", "conteudo limpo", "--priority", "urgent",
                 "--apply", "--base-dir", str(d)]) == 5


def test_cli_compact_e_report(tmp_path):
    d = tmp_path / "mem"
    main(["--add", "a limpo", "--apply", "--base-dir", str(d)])
    assert main(["--compact", "--apply", "--base-dir", str(d)]) == 0
    assert (d / "memory.compacted.jsonl").exists()
    assert main(["--report", "--apply", "--base-dir", str(d)]) == 0
    assert list((d / "reports").glob("report_*.md"))


def test_cli_saida_json(tmp_path, capsys):
    d = tmp_path / "mem"
    main(["--add", "conteudo json", "--apply", "--base-dir", str(d)])
    capsys.readouterr()
    rc = main(["--list", "--json", "--base-dir", str(d)])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list) and len(data) == 1
