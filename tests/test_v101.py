"""v1.0.1 — boot leve, doutor --consertar, backup total, códigos de erro."""
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from nomos import cli
from nomos.simple import backup_total as bt
from nomos.simple import doutor, erros

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _iso(nomos_home, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    yield


# ---------------- boot leve ----------------

def test_import_da_cli_nao_carrega_pesados():
    """cryptography/argon2/cognição só entram quando um comando precisa."""
    codigo = (
        "import sys, nomos.cli;"
        "pesados = [m for m in sys.modules if any(x in m for x in"
        " ('cryptography', 'argon2', 'nomos.cognition', 'sqlite3'))];"
        "assert not pesados, pesados; print('LIMPO')"
    )
    r = subprocess.run([sys.executable, "-c", codigo],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "LIMPO" in r.stdout


def test_version_rapida_em_subprocesso():
    import time
    t0 = time.perf_counter()
    r = subprocess.run([sys.executable, "-m", "nomos.cli", "--version"],
                       capture_output=True, text=True, timeout=60)
    dt = time.perf_counter() - t0
    assert r.returncode == 0 and "nomos" in r.stdout
    assert dt < 3.0   # folga enorme p/ CI; local fica ~40 ms


# ---------------- doutor --consertar ----------------

def _sabotar(nomos_home):
    nomos_home.mkdir(parents=True, exist_ok=True)
    (nomos_home / "localidade.json").write_text("{quebrado")
    (nomos_home / "rotinas.json").write_text("nem json")
    (nomos_home / "skills_estado.json").write_text("{tambem nao")


def test_consertar_detecta_e_preserva_originais(nomos_home):
    _sabotar(nomos_home)
    achados = doutor.diagnosticar_consertos(nomos_home)
    ids = {a["id"] for a in achados}
    assert {"arquivo:localidade.json", "arquivo:rotinas.json",
            "arquivo:skills_estado.json"} <= ids
    rc, feitos = doutor.consertar(nomos_home, confirmar=lambda: True,
                                  say=lambda *_: None)
    assert rc == 0 and len(feitos) >= 3
    # originais preservados; recriados são válidos e SEGUROS
    assert (nomos_home / "localidade.json.corrompido").exists()
    from nomos.kernel import localidade
    assert localidade.esta_ligado(nomos_home) is True     # padrão mais seguro
    assert json.loads((nomos_home / "rotinas.json").read_text()) == {"rotinas": []}
    # idempotente
    assert doutor.diagnosticar_consertos(nomos_home) == []


def test_consertar_sem_confirmacao_nao_muda_nada(nomos_home):
    _sabotar(nomos_home)
    rc, feitos = doutor.consertar(nomos_home, confirmar=lambda: False,
                                  say=lambda *_: None)
    assert rc == 3 and feitos == []
    assert (nomos_home / "localidade.json").read_text() == "{quebrado"


def test_cli_consertar_sem_tty_lista_e_nega(nomos_home, capsys):
    assert cli.main(["init"]) == 0
    (nomos_home / "rotinas.json").write_text("{quebrado")
    rc = cli.main(["doutor", "--consertar"])
    assert rc == 3
    saida = capsys.readouterr()
    assert "rotinas.json" in saida.out                 # listou o que faria
    assert "NOMOS-E009" in saida.err                   # e negou com código
    assert (nomos_home / "rotinas.json").read_text() == "{quebrado"


def test_consertar_nada_a_fazer(nomos_home, capsys):
    assert cli.main(["init"]) == 0
    assert cli.main(["doutor", "--consertar"]) == 0
    assert "tudo íntegro" in capsys.readouterr().out


# ---------------- backup total ----------------

def _povoar(nomos_home):
    nomos_home.mkdir(parents=True, exist_ok=True)
    (nomos_home / "agent.json").write_text('{"agent_name": "Atlas"}')
    (nomos_home / "logs").mkdir(exist_ok=True)
    (nomos_home / "logs" / "audit.jsonl").write_text('{"event": "x"}\n')
    (nomos_home / "modelos").mkdir(exist_ok=True)
    (nomos_home / "modelos" / "grande.gguf").write_bytes(b"G" * 1024)


def test_backup_total_roundtrip(nomos_home, tmp_path):
    _povoar(nomos_home)
    destino = tmp_path / "meu-nomos.backup"
    n, excluidas = bt.criar(nomos_home, destino, "senha-forte-123")
    assert n == 2 and "modelos/" in excluidas          # modelo NÃO vai
    assert b"Atlas" not in destino.read_bytes()        # cifrado de verdade

    novo_home = tmp_path / "novo-home"
    restaurados, guardado = bt.restaurar(novo_home, destino, "senha-forte-123")
    assert restaurados == 2 and guardado == ""
    assert json.loads((novo_home / "agent.json").read_text())["agent_name"] == "Atlas"


def test_backup_senha_errada_e_nao_sobrescreve(nomos_home, tmp_path):
    _povoar(nomos_home)
    destino = tmp_path / "b.backup"
    bt.criar(nomos_home, destino, "senha-forte-123")
    with pytest.raises(bt.BackupTotalError, match="senha incorreta"):
        bt.restaurar(tmp_path / "outro", destino, "senha-errada-000")
    # home com conteúdo sem permissão explícita => recusa e nada muda
    with pytest.raises(bt.BackupTotalError, match="não está vazio"):
        bt.restaurar(nomos_home, destino, "senha-forte-123")
    assert (nomos_home / "agent.json").exists()
    # com permissão: restaura e PRESERVA o anterior
    n, guardado = bt.restaurar(nomos_home, destino, "senha-forte-123",
                               permitir_sobrescrever=True)
    assert n == 2 and Path(guardado).exists()
    assert (Path(guardado) / "agent.json").exists()


def test_backup_nao_sobrescreve_arquivo_de_destino(nomos_home, tmp_path):
    _povoar(nomos_home)
    destino = tmp_path / "b.backup"
    destino.write_text("já existe")
    with pytest.raises(bt.BackupTotalError, match="não sobrescrevo"):
        bt.criar(nomos_home, destino, "senha-forte-123")


def test_cli_backup_criar_com_env(nomos_home, monkeypatch, tmp_path, capsys):
    assert cli.main(["init"]) == 0
    monkeypatch.setenv("NOMOS_BACKUP_SENHA", "senha-forte-123")
    destino = tmp_path / "tudo.backup"
    assert cli.main(["backup", "criar", str(destino)]) == 0
    assert destino.exists()
    assert cli.main(["backup", "inspecionar", str(destino)]) == 0
    assert "policy.json" in capsys.readouterr().out


def test_cli_backup_restaurar_home_cheio_sem_tty_nega(nomos_home, monkeypatch,
                                                      tmp_path, capsys):
    assert cli.main(["init"]) == 0
    monkeypatch.setenv("NOMOS_BACKUP_SENHA", "senha-forte-123")
    destino = tmp_path / "t.backup"
    assert cli.main(["backup", "criar", str(destino)]) == 0
    rc = cli.main(["backup", "restaurar", str(destino)])
    assert rc == 3 and "NOMOS-E002" in capsys.readouterr().err


# ---------------- códigos de erro ----------------

def test_codigos_usados_estao_catalogados_e_documentados():
    usados = set()
    import re
    for f in (RAIZ / "src" / "nomos").rglob("*.py"):
        usados |= set(re.findall(r'fmt\("(E\d{3})"', f.read_text()))
    assert usados, "nenhum código em uso?"
    assert usados <= set(erros.CODIGOS), f"não catalogado: {usados - set(erros.CODIGOS)}"
    doc = (RAIZ / "docs" / "ERROS.md").read_text()
    faltam_doc = {c for c in erros.CODIGOS if f"NOMOS-{c}" not in doc}
    assert not faltam_doc, f"sem documentação: {faltam_doc}"


def test_fluxos_reais_emitem_codigo(nomos_home, capsys):
    assert cli.main(["init"]) == 0
    cli.main(["arquivo", "/nao/existe.txt"])
    assert "NOMOS-E003" in capsys.readouterr().err
    cli.main(["atualizar"])
    assert "NOMOS-E002" in capsys.readouterr().out


# ---------------- motor prefer-binary ----------------

def test_instalar_motor_usa_prefer_binary(monkeypatch):
    from nomos.cognition import embutido as emb
    monkeypatch.setattr(emb, "llama_disponivel", lambda: False)
    capturado = {}

    def fake_run(argv, **kw):
        capturado["argv"] = argv
        class R:
            returncode = 0
        return R()
    monkeypatch.setattr(emb.subprocess, "run", fake_run)
    ok, msg = emb.instalar_motor()
    assert ok and "--prefer-binary" in capturado["argv"]


def test_instalar_motor_falha_orienta_sem_compilador(monkeypatch):
    from nomos.cognition import embutido as emb
    monkeypatch.setattr(emb, "llama_disponivel", lambda: False)

    def fake_run(argv, **kw):
        class R:
            returncode = 1
        return R()
    monkeypatch.setattr(emb.subprocess, "run", fake_run)
    ok, msg = emb.instalar_motor()
    assert not ok and "compilador" in msg and "Ollama" in msg
