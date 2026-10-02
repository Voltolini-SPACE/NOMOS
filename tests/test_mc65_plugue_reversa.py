"""MC65 — o ponto de plugue `nomos reversa` continua funcionando.

O componente «NOMOS Reversa» vive em repositório próprio (`nomos_reversa`) e
plugar no ecossistema é o critério de aceite da regra: encaixa rápido e fácil.

Estes testes travam o contrato do plugue:
- o subcomando existe e se anuncia;
- com o componente instalado, o comando mapeia e NÃO executa o alvo;
- sem o componente instalado, o comando AVISA com a linha de instalação —
  nunca um traceback;
- o plugue não expõe nenhuma flag de mutação.
"""
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from nomos.cli import EXIT_ERROR, cmd_reversa

ROOT = Path(__file__).resolve().parent.parent


def _cli(args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "nomos.cli", *args],
        capture_output=True, text=True, cwd=str(cwd or ROOT), timeout=120,
    )


# 1. o subcomando está registrado e se anuncia
def test_subcomando_reversa_existe():
    proc = _cli(["reversa", "--help"])
    assert proc.returncode == 0, proc.stderr
    assert "alvo" in proc.stdout
    assert "--json" in proc.stdout


# 2. sem o componente instalado: aviso claro, sem traceback
def test_sem_componente_avisa_com_linha_de_instalacao(monkeypatch, capsys, tmp_path):
    # `sys.modules[nome] = None` faz `import nome` levantar ImportError.
    monkeypatch.setitem(sys.modules, "nomos_reversa", None)
    args = SimpleNamespace(alvo=str(tmp_path), saida=None, json=False)

    codigo = cmd_reversa({}, args)

    capturado = capsys.readouterr()
    assert codigo == EXIT_ERROR
    assert "NOMOS Reversa" in capturado.err
    assert "pip install nomos-reversa" in capturado.err
    assert "Traceback" not in capturado.err


# 3. com o componente instalado: mapeia e NÃO executa o alvo
def test_com_componente_mapeia_e_nao_executa(tmp_path):
    pytest.importorskip("nomos_reversa",
                        reason="componente «NOMOS Reversa» não instalado")
    alvo = tmp_path / "terceiro"
    alvo.mkdir()
    sentinela = alvo / "EXECUTOU"
    script = alvo / "perigoso.sh"
    script.write_text(f"#!/bin/sh\ntouch {sentinela}\n")
    script.chmod(0o755)

    proc = _cli(["reversa", str(alvo), "--json"])

    assert proc.returncode == 0, proc.stderr
    dados = json.loads(proc.stdout)
    assert dados["read_only"] is True
    assert dados["executed_target"] is False
    assert not sentinela.exists(), "o plugue executou o alvo"


# 4. o alvo não é alterado pelo comando do ecossistema
def test_plugue_nao_escreve_no_alvo(tmp_path):
    pytest.importorskip("nomos_reversa",
                        reason="componente «NOMOS Reversa» não instalado")
    alvo = tmp_path / "alvo"
    alvo.mkdir()
    (alvo / "a.sh").write_text("echo oi\n")
    antes = sorted(p.name for p in alvo.iterdir())

    _cli(["reversa", str(alvo)])

    assert sorted(p.name for p in alvo.iterdir()) == antes


# 5. o plugue não expõe flag de mutação
def test_plugue_nao_expoe_mutacao():
    proc = _cli(["reversa", "--help"])
    assert proc.returncode == 0
    for proibido in ("--push", "--commit", "--apply", "--install", "--exec"):
        assert proibido not in proc.stdout, f"flag proibida exposta: {proibido}"


# 6. relatório legível quando não se pede JSON
def test_relatorio_legivel(tmp_path):
    pytest.importorskip("nomos_reversa",
                        reason="componente «NOMOS Reversa» não instalado")
    alvo = tmp_path / "alvo"
    alvo.mkdir()
    (alvo / "a.txt").write_text("oi\n")

    proc = _cli(["reversa", str(alvo)])

    assert proc.returncode == 0, proc.stderr
    assert "# Mapa de" in proc.stdout
