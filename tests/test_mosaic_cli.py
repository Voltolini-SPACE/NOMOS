"""NOMOS Mosaic — CLI (dry-run padrão, fail-closed)."""
import pytest

from nomos.mosaic.cli import main


def test_cli_add_dry_run_nao_grava(tmp_path):
    d = tmp_path / "m"
    assert main(["--add", "mail.google.com", "--base-dir", str(d)]) == 0
    assert not (d / "screens.json").exists()


def test_cli_add_apply_e_list(tmp_path, capsys):
    d = tmp_path / "m"
    assert main(["--add", "mail.google.com", "--label", "Gmail",
                 "--apply", "--base-dir", str(d)]) == 0
    assert (d / "screens.json").exists()
    capsys.readouterr()
    assert main(["--list", "--base-dir", str(d)]) == 0
    assert "Gmail" in capsys.readouterr().out


def test_cli_scan_e_panel_apply(tmp_path):
    d = tmp_path / "m"
    main(["--add", "instagram.com", "--apply", "--base-dir", str(d)])
    assert main(["--scan", "--apply", "--base-dir", str(d)]) == 0
    assert main(["--panel", "--apply", "--base-dir", str(d)]) == 0
    assert (d / "panel.html").exists()


def test_cli_act_fail_closed(tmp_path, capsys):
    d = tmp_path / "m"
    main(["--add", "mail.google.com", "--apply", "--base-dir", str(d)])
    capsys.readouterr()
    # ação inválida → saída 3 fail-closed
    assert main(["--act", "scr_x", "--action", "NUKE", "--apply", "--base-dir", str(d)]) == 3


def test_cli_demo_apply(tmp_path):
    d = tmp_path / "m"
    assert main(["--demo", "--apply", "--base-dir", str(d)]) == 0
    assert (d / "screens.json").exists()


def test_cli_sem_acao_fail_closed(tmp_path):
    with pytest.raises(SystemExit) as ei:
        main(["--base-dir", str(tmp_path / "m")])
    assert ei.value.code == 2
