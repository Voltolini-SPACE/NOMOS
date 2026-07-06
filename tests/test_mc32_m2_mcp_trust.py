"""MC32/M2 — catálogo + confiança de servers MCP (registro por impressão)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from nomos.interface import mcp_catalogo as cat

ROOT = Path(__file__).resolve().parent.parent


def _man(nome="nomos-espelho", **extra) -> dict:
    return {"nome": nome,
            "comando": [sys.executable, "-m", "nomos", "mcp", "servir"],
            "nivel_padrao": "A0", **extra}


def _escrever(tmp_path: Path, manifesto: dict) -> Path:
    p = tmp_path / "manifesto.json"
    p.write_text(json.dumps(manifesto), encoding="utf-8")
    return p


def _cli(args, home: Path, entrada=None):
    return subprocess.run(
        [sys.executable, "-m", "nomos", *args],
        input=entrada, capture_output=True, text=True, timeout=90,
        cwd=str(ROOT), env={"NOMOS_HOME": str(home), "PATH": ""},
    )


# --- unidade: impressão, confiar, alteração, revogar ---
def test_impressao_estavel_e_sensivel(tmp_path):
    a = cat.impressao(_man())
    assert a == cat.impressao(_man())                 # determinística
    assert a != cat.impressao(_man(nivel_padrao="A1"))  # muda com o conteúdo


def test_status_ciclo_completo(tmp_path):
    m = _man()
    assert cat.status(tmp_path, m) == "experimental"
    cat.confiar(tmp_path, m)
    assert cat.status(tmp_path, m) == "confiavel"
    # manifesto alterado deixa de ser confiável (impressão diferente)
    assert cat.status(tmp_path, _man(nivel_padrao="A5")) == "experimental"
    cat.revogar(tmp_path, m)
    assert cat.status(tmp_path, m) == "revogado"


def test_revogado_nao_pode_ser_reconfiado(tmp_path):
    m = _man()
    cat.confiar(tmp_path, m)
    cat.revogar(tmp_path, m)
    with pytest.raises(cat.CatalogoErro, match="REVOGADO"):
        cat.confiar(tmp_path, m)


def test_catalogo_corrompido_fail_closed(tmp_path):
    (tmp_path / cat.ARQUIVO).write_text("{ lixo", encoding="utf-8")
    with pytest.raises(cat.CatalogoErro):
        cat.status(tmp_path, _man())


# --- CLI: experimental exige ACEITO O RISCO; confiar persiste; revogar bloqueia ---
def test_cli_conectar_experimental_sem_tty_nega(tmp_path):
    man = _escrever(tmp_path, _man())
    proc = _cli(["mcp", "conectar", str(man)], tmp_path)
    assert proc.returncode == 3
    assert "NOMOS-E002" in proc.stderr and "experimental" in proc.stderr


def _confiar_no_catalogo(tmp_path, manifesto_arquivo):
    """Registra confiança pelo módulo (a CLI 'confiar' exige TTY real)."""
    from nomos.interface import mcp_client as mc
    cat.confiar(tmp_path, mc.carregar_manifesto(manifesto_arquivo))


def test_cli_confiar_sem_tty_nega(tmp_path):
    man = _escrever(tmp_path, _man())
    proc = _cli(["mcp", "confiar", str(man)], tmp_path)     # sem TTY
    assert proc.returncode == 3 and "NOMOS-E002" in proc.stderr
    assert cat.status(tmp_path, _man()) == "experimental"   # nada registrado


def test_cli_confiavel_conecta_sem_tty(tmp_path):
    man = _escrever(tmp_path, _man())
    _confiar_no_catalogo(tmp_path, man)
    conn = _cli(["mcp", "conectar", str(man)], tmp_path)     # confiável ⇒ ok
    assert conn.returncode == 0
    assert "confiável" in conn.stdout and "nomos_status" in conn.stdout


def test_cli_revogar_bloqueia_conexao(tmp_path):
    man = _escrever(tmp_path, _man())
    _confiar_no_catalogo(tmp_path, man)
    rev = _cli(["mcp", "revogar", str(man)], tmp_path)
    assert rev.returncode == 0 and "revogado" in rev.stdout
    conn = _cli(["mcp", "conectar", str(man)], tmp_path)
    assert conn.returncode == 3 and "REVOGADO" in conn.stderr


def test_cli_catalogo_lista(tmp_path):
    man = _escrever(tmp_path, _man("meu-server"))
    _confiar_no_catalogo(tmp_path, man)
    proc = _cli(["mcp", "catalogo"], tmp_path)
    assert proc.returncode == 0 and "meu-server" in proc.stdout
