"""MC26-UX — `nomos conselho diagnostico` e `/conselho diagnostico`.

O diagnóstico é a prova executável do "evidência, não promessa": ele LÊ a trava
`REAL_LOCAL_ENGINE_EXECUTION_ENABLED` ao vivo (via `real_execution_enabled()`) e
reporta. Provas:

- com a trava em `False` (por construção), reporta FAIL-CLOSED e `= false`;
- se a trava fosse `True`, a saída MUDARIA (monkeypatch) — logo é leitura viva,
  não string fixa;
- nunca chama `LocalExecutionHarness.execute` (não executa nada);
- recusa flags proibidas sem ecoar; não persiste; funciona igual no chat.

Pureza (AST): `cli_diag` importa só a LEITURA da trava e o contrato de flags
proibidas — nada de rede/subprocess/cloud/kernel/orquestrador, FS, env,
tempo ou random.
"""
import ast
import io

import pytest

from nomos import cli
from nomos.council import cli_diag, local_harness
from nomos.council.chat_dry_run import handle_chat_dry_run

_SENSIVEL = "PROMPT-SENSIVEL-diag-321-nao-pode-vazar"


@pytest.fixture(autouse=True)
def _nao_interativo(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    yield


def _run(capsys, *argv):
    rc = cli.main(list(argv))
    return rc, capsys.readouterr().out


# --------------------------------------------------------------------------
# Comportamento — CLI e chat
# --------------------------------------------------------------------------

def test_cli_diagnostico_reporta_fail_closed(capsys):
    rc, out = _run(capsys, "conselho", "diagnostico")
    assert cli_diag.DIAG_CODE in out
    assert "REAL_LOCAL_ENGINE_EXECUTION_ENABLED = false" in out
    assert "FAIL-CLOSED" in out
    assert rc == cli_diag.DIAG_EXIT_CODE


def test_chat_diagnostico_reporta_fail_closed():
    out = handle_chat_dry_run("/conselho diagnostico")
    assert cli_diag.DIAG_CODE in out
    assert "= false" in out
    assert "FAIL-CLOSED" in out


# --------------------------------------------------------------------------
# A PROVA: é leitura VIVA — se a trava mudasse, a saída mudaria
# --------------------------------------------------------------------------

def test_diagnostico_le_a_trava_ao_vivo(monkeypatch):
    # com a trava real (False): fail-closed
    assert "= false" in cli_diag.diagnostico_message()
    # se alguém ligasse a trava, o diagnóstico GRITARIA (prova de leitura viva)
    monkeypatch.setattr(local_harness, "REAL_LOCAL_ENGINE_EXECUTION_ENABLED", True)
    alerta = cli_diag.diagnostico_message()
    assert "= true" in alerta
    assert "ATENÇÃO" in alerta
    # e volta ao normal quando o monkeypatch sai de escopo (garantido pelo pytest)


def test_diagnostico_json_reflete_a_trava_ao_vivo(capsys, monkeypatch):
    import json
    # trava real (False): JSON diz fail_closed=true
    rc, out = _run(capsys, "conselho", "diagnostico", "--json")
    d = json.loads(out)
    assert d["schema"] == "nomos.council.diagnostico.v1"
    assert d["real_engine_execution_enabled"] is False
    assert d["fail_closed"] is True
    # se a trava ligasse, o JSON mudaria (leitura viva)
    monkeypatch.setattr(local_harness, "REAL_LOCAL_ENGINE_EXECUTION_ENABLED", True)
    assert cli_diag.diagnostico_json().count("true") >= 1
    d2 = __import__("json").loads(cli_diag.diagnostico_json())
    assert d2["real_engine_execution_enabled"] is True
    assert d2["fail_closed"] is False


def test_diagnostico_nunca_chama_o_harness_de_execucao(capsys, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("diagnostico não pode executar o harness")

    monkeypatch.setattr(local_harness.LocalExecutionHarness, "execute", boom)
    rc, out = _run(capsys, "conselho", "diagnostico")
    assert cli_diag.DIAG_CODE in out
    # a trava real segue desligada
    assert local_harness.real_execution_enabled() is False


# --------------------------------------------------------------------------
# Segurança — flags proibidas sem eco, sem persistência
# --------------------------------------------------------------------------

def test_diagnostico_recusa_flag_proibida_sem_ecoar(capsys):
    for flag in ("--real", "--enable", "--cloud", "--engine-real"):
        rc, out = _run(capsys, "conselho", "diagnostico", flag)
        assert cli_diag.DIAG_DENIED_CODE in out, flag
        assert flag not in out, flag
        assert rc == cli_diag.DIAG_DENIED_EXIT_CODE, flag


def test_diagnostico_nao_ecoa_posicional(capsys):
    rc, out = _run(capsys, "conselho", "diagnostico", _SENSIVEL)
    assert _SENSIVEL not in out


def test_diagnostico_nao_persiste(capsys, tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("NOMOS_HOME", str(home))
    antes = list(home.rglob("*"))
    _run(capsys, "conselho", "diagnostico")
    assert list(home.rglob("*")) == antes == []


# --------------------------------------------------------------------------
# Pureza / segurança por AST do módulo cli_diag
# --------------------------------------------------------------------------

def _imports():
    src = open(cli_diag.__file__, encoding="utf-8").read()
    nomes = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            nomes.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            nomes.add(node.module)
    return nomes


def _fonte():
    return open(cli_diag.__file__, encoding="utf-8").read()


def test_diag_module_nao_importa_rede_subprocess_cloud():
    proibidos = {"socket", "ssl", "http", "urllib", "requests", "httpx",
                 "aiohttp", "subprocess", "threading", "asyncio", "multiprocessing"}
    assert not (_imports() & proibidos), _imports() & proibidos
    prefixos = ("openai", "anthropic", "google", "ollama", "torch",
                "nomos.kernel", "nomos.cognition", "nomos.runtime", "nomos.agents",
                "nomos.ext", "nomos.council.orchestrator", "nomos.council.policy_gate",
                "nomos.council.audit_envelope")
    usados = _imports()
    ruins = [m for m in usados if any(m == p or m.startswith(p + ".") for p in prefixos)]
    assert not ruins, ruins


def test_diag_module_so_le_a_trava():
    # do harness, importa SÓ a função de leitura da trava — nunca a classe de
    # execução — e não chama `.execute(` em lugar nenhum.
    src = _fonte()
    assert "real_execution_enabled" in src
    assert ".execute(" not in src
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom) and node.module == "nomos.council.local_harness":
            nomes = {a.name for a in node.names}
            assert nomes == {"real_execution_enabled"}, nomes


def test_diag_module_nao_toca_fs_env_tempo_random():
    src = _fonte()
    for proibido in ("environ", "getenv", "open(", "write_text", "write_bytes",
                     ".now(", "random.", "time."):
        assert proibido not in src, proibido
    usados = _imports()
    for mod in ("time", "random", "secrets", "os"):
        assert mod not in usados, mod
