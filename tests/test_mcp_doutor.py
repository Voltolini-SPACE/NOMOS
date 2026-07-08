"""MC48 — `nomos mcp doutor`: check-up SÓ-LEITURA dos conectores.

Garante: lista os conectores de exemplo com estado de confiança; reporta
credenciais apenas por PRESENÇA no ambiente (o **valor** jamais aparece);
honesto quando não há exemplos; não grava nada; saída --json válida.
"""
import io
import json
from pathlib import Path

import pytest

from nomos import cli
from nomos.interface import mcp_catalogo as cat

RAIZ = Path(__file__).resolve().parent.parent
EXEMPLOS = RAIZ / "examples" / "mcp"
_SEGREDO = "TOKEN-SUPER-SECRETO-nao-pode-vazar-999"

_ENVS = ("NOMOS_TELEGRAM_TOKEN", "NOMOS_WHATSAPP_TOKEN", "NOMOS_WHATSAPP_PHONE_ID",
         "NOMOS_SMTP_HOST", "NOMOS_SMTP_USER", "NOMOS_SMTP_PASSWORD", "NOMOS_SMTP_FROM")


@pytest.fixture(autouse=True)
def _iso(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    for k in _ENVS:                    # ambiente limpo por padrão
        monkeypatch.delenv(k, raising=False)
    yield


def test_diagnostico_lista_os_tres(nomos_home):
    d = cat.diagnostico_conectores(nomos_home, raiz=EXEMPLOS)
    nomes = sorted(c["nome"] for c in d["conectores"])
    assert nomes == ["email-smtp", "telegram-bot", "whatsapp-cloud"]
    tel = next(c for c in d["conectores"] if c["nome"] == "telegram-bot")
    assert tel["credenciais_ok"] is False              # sem env setada
    assert "NOMOS_TELEGRAM_TOKEN" in tel["env_faltando"]
    assert tel["status"] == "experimental"
    assert tel["interpretador_ok"] is True             # python3 existe


def test_credencial_presente_sem_vazar_o_valor(nomos_home, monkeypatch):
    monkeypatch.setenv("NOMOS_TELEGRAM_TOKEN", _SEGREDO)
    d = cat.diagnostico_conectores(nomos_home, raiz=EXEMPLOS)
    tel = next(c for c in d["conectores"] if c["nome"] == "telegram-bot")
    assert tel["credenciais_ok"] is True
    assert tel["env_faltando"] == []
    # o VALOR jamais entra na estrutura — só o NOME da variável
    assert _SEGREDO not in json.dumps(d)
    assert "NOMOS_TELEGRAM_TOKEN" in tel["env"]


def test_honesto_sem_exemplos(nomos_home, tmp_path):
    vazio = tmp_path / "sem_exemplos"
    vazio.mkdir()
    d = cat.diagnostico_conectores(nomos_home, raiz=vazio)
    assert d["conectores"] == []
    assert d["raiz"] == str(vazio)


def test_doutor_cli_nao_vaza_valor_e_e_read_only(nomos_home, monkeypatch, capsys):
    monkeypatch.setenv("NOMOS_TELEGRAM_TOKEN", _SEGREDO)
    monkeypatch.chdir(RAIZ)                    # acha examples/ pelo cwd
    cli.main(["mcp", "doutor"])                # 1ª vez: bootstrap normal do home
    capsys.readouterr()
    antes = sorted(p.as_posix() for p in nomos_home.rglob("*"))
    rc = cli.main(["mcp", "doutor"])           # 2ª vez: doutor não muda nada
    out = capsys.readouterr().out
    assert rc == 0
    assert "telegram-bot" in out
    assert _SEGREDO not in out                 # nunca o valor
    assert "NOMOS_TELEGRAM_TOKEN" in out       # só o nome
    depois = sorted(p.as_posix() for p in nomos_home.rglob("*"))
    assert antes == depois                     # idempotente: nada gravado
    assert not (nomos_home / "mcp_catalogo.json").exists()   # não cria trust store


def test_doutor_cli_json(nomos_home, monkeypatch, capsys):
    monkeypatch.chdir(RAIZ)
    rc = cli.main(["mcp", "doutor", "--json"])
    d = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert len(d["conectores"]) == 3
    assert "raiz" in d and "confiaveis" in d
