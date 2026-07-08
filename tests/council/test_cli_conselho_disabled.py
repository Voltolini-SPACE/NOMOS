"""MC14-UX — `nomos conselho` nasce DESABILITADO (fail-closed).

Prova de comportamento: o comando existe, mas qualquer uso devolve a mensagem
genérica de bloqueio; nunca ecoa o prompt/flags do usuário; nunca chama o
orquestrador, o harness de execução real, nem policy/vault/audit reais; não
persiste nada; e nenhuma flag/variável de ambiente o habilita.

Prova de pureza (AST): o módulo `nomos.council.cli_disabled` não importa rede/
subprocess/threading/asyncio/SDK de nuvem/motor, não toca FS/env, não usa
tempo/random.
"""
import ast
import io

import pytest

from nomos import cli
from nomos.council import cli_disabled

_SENSIVEL = "PROMPT-SENSIVEL-abc123-nao-pode-vazar"


@pytest.fixture(autouse=True)
def _nao_interativo(monkeypatch):
    # Garante que nada dependa de TTY; o caminho desabilitado nem lê stdin.
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    yield


def _run(capsys, *argv):
    rc = cli.main(list(argv))
    out = capsys.readouterr().out
    return rc, out


# --------------------------------------------------------------------------
# Comportamento
# --------------------------------------------------------------------------

def test_cli_conselho_disabled(capsys):
    rc, out = _run(capsys, "conselho")
    assert cli_disabled.DISABLED_CODE in out
    assert "não está habilitado" in out
    assert rc == cli_disabled.DISABLED_EXIT_CODE


def test_cli_conselho_revisar_disabled(capsys):
    # `status` foi finalizado (informativo) na MC23-UX; `revisar` — que exigiria
    # execução real — SEGUE desabilitado e declara as travas fail-closed.
    rc, out = _run(capsys, "conselho", "revisar", "arquivo.md")
    assert cli_disabled.DISABLED_CODE in out
    assert "CLI_ENABLED=false" in out
    assert rc == cli_disabled.DISABLED_EXIT_CODE


def test_cli_conselho_raiz_aponta_comandos_uteis(capsys):
    # MC25-UX: a raiz (e o fallback) deixou de mandar "leia só a doc" e agora
    # aponta o que JÁ funciona — sem afrouxar as travas.
    rc, out = _run(capsys, "conselho")
    assert "conselho status" in out
    assert "conselho modos" in out
    assert "conselho simular" in out
    assert "CLI_ENABLED=false" in out          # travas seguem impressas


def test_cli_conselho_perguntar_does_not_echo_prompt(capsys):
    rc, out = _run(capsys, "conselho", "perguntar", _SENSIVEL)
    assert _SENSIVEL not in out
    assert "SENSIVEL" not in out
    assert cli_disabled.DISABLED_CODE in out


def test_cli_conselho_disabled_subcommand_does_not_echo_prompt(capsys):
    # `simular` foi habilitado na MC15 (dry-run); os DEMAIS subcomandos
    # continuam desabilitados e nunca ecoam o prompt. Usamos `perguntar`.
    rc, out = _run(capsys, "conselho", "perguntar", _SENSIVEL)
    assert _SENSIVEL not in out
    assert cli_disabled.DISABLED_CODE in out


def test_cli_conselho_flags_cannot_enable(capsys):
    for flag in ("--enable", "--ativar", "--force", "--real", "--executar",
                 "--unsafe", "--cloud"):
        rc, out = _run(capsys, "conselho", "perguntar", _SENSIVEL, flag)
        assert cli_disabled.DISABLED_CODE in out, flag
        assert "CLI_ENABLED=false" in out, flag
        assert _SENSIVEL not in out, flag
        assert flag not in out, flag


def test_cli_conselho_output_declares_no_real_execution(capsys):
    rc, out = _run(capsys, "conselho")
    for marca in ("CLI_ENABLED=false", "REAL_ENGINE_EXECUTION=false",
                  "REAL_POLICY=false", "REAL_AUDIT=false", "REAL_VAULT=false",
                  "PERSISTENCE=false"):
        assert marca in out, marca


def test_cli_conselho_does_not_call_orchestrator(capsys, monkeypatch):
    import nomos.council.orchestrator as orch

    def boom(*a, **k):
        raise AssertionError("orquestrador não pode ser chamado pela CLI desabilitada")

    monkeypatch.setattr(orch.CouncilOrchestratorDryRun, "run", boom)
    rc, out = _run(capsys, "conselho", "perguntar", _SENSIVEL)
    assert cli_disabled.DISABLED_CODE in out


def test_cli_conselho_does_not_call_harness(capsys, monkeypatch):
    import nomos.council.local_harness as harness

    def boom(*a, **k):
        raise AssertionError("harness real não pode ser chamado pela CLI desabilitada")

    monkeypatch.setattr(harness.LocalExecutionHarness, "execute", boom)
    # subcomando desabilitado (`perguntar`) — nunca toca o harness
    rc, out = _run(capsys, "conselho", "perguntar", _SENSIVEL)
    assert cli_disabled.DISABLED_CODE in out


def test_cli_conselho_does_not_call_policy_vault_audit(capsys, monkeypatch):
    # O caminho desabilitado curto-circuita ANTES de _paths(): nenhum
    # Vault/PolicyEngine/AuditLog é sequer construído.
    def boom(*a, **k):
        raise AssertionError("_paths (vault/policy/audit) não pode ser construído")

    monkeypatch.setattr(cli, "_paths", boom)
    rc, out = _run(capsys, "conselho", "perguntar", _SENSIVEL)
    assert cli_disabled.DISABLED_CODE in out
    assert rc == cli_disabled.DISABLED_EXIT_CODE


def test_cli_conselho_no_env_enable(capsys, monkeypatch):
    for var in ("MOTOR_COUNCIL_CLI_ENABLED", "NOMOS_COUNCIL_ENABLE",
                "NOMOS_MC_CLI_ENABLED", "COUNCIL_ENABLE"):
        monkeypatch.setenv(var, "1")
    rc, out = _run(capsys, "conselho")
    assert "CLI_ENABLED=false" in out
    assert cli_disabled.MOTOR_COUNCIL_CLI_ENABLED is False


def test_cli_conselho_no_persistence(capsys, tmp_path, monkeypatch):
    # Rodar o comando não pode criar nenhum arquivo em um HOME limpo.
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("NOMOS_HOME", str(home))
    antes = list(home.rglob("*"))
    rc, out = _run(capsys, "conselho", "perguntar", _SENSIVEL)
    depois = list(home.rglob("*"))
    assert antes == depois == []
    assert cli_disabled.DISABLED_CODE in out


def test_cli_conselho_help_mentions_disabled_or_prerelease(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out.lower()
    assert "conselho" in out
    assert ("desabilitado" in out) or ("pré-release" in out) or ("pre-release" in out)


def test_cli_conselho_json_if_supported_is_redacted(capsys):
    # A CLI desabilitada não suporta JSON; mesmo com --json, a saída é a
    # mensagem genérica e não contém nada do que o usuário digitou ("redacted").
    rc, out = _run(capsys, "conselho", "perguntar", _SENSIVEL, "--json")
    assert _SENSIVEL not in out
    assert cli_disabled.DISABLED_CODE in out


def test_cli_conselho_unknown_subcommand_fail_closed(capsys):
    rc, out = _run(capsys, "conselho", "frobnicate", _SENSIVEL)
    assert cli_disabled.DISABLED_CODE in out
    assert _SENSIVEL not in out
    assert rc == cli_disabled.DISABLED_EXIT_CODE


# --------------------------------------------------------------------------
# Pureza / segurança por AST
# --------------------------------------------------------------------------

def _imports():
    src = open(cli_disabled.__file__, encoding="utf-8").read()
    nomes = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            nomes.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            nomes.add(node.module)
    return nomes


def _fonte():
    return open(cli_disabled.__file__, encoding="utf-8").read()


def test_cli_conselho_module_does_not_import_network():
    proibidos = {"socket", "ssl", "http", "http.client", "urllib",
                 "urllib.request", "requests", "httpx", "aiohttp", "ftplib",
                 "smtplib"}
    assert not (_imports() & proibidos), _imports() & proibidos


def test_cli_conselho_module_does_not_import_subprocess_threading_asyncio():
    proibidos = {"subprocess", "threading", "multiprocessing", "asyncio",
                 "concurrent.futures", "signal"}
    assert not (_imports() & proibidos), _imports() & proibidos


def test_cli_conselho_module_does_not_import_cloud_clients():
    usados = _imports()
    prefixos = ("openai", "anthropic", "google", "google.generativeai", "gemini",
                "cohere", "boto3", "azure", "vertexai", "ollama", "llama_cpp",
                "transformers", "torch")
    ruins = [m for m in usados if any(m == p or m.startswith(p + ".") for p in prefixos)]
    assert not ruins, ruins


def test_cli_conselho_module_does_not_import_council_runtime():
    # Não importa orquestrador/harness/policy/audit/vault reais nem router/motores.
    usados = _imports()
    prefixos = ("nomos.council.orchestrator", "nomos.council.local_harness",
                "nomos.council.policy_gate", "nomos.council.audit_envelope",
                "nomos.kernel", "nomos.cognition", "nomos.runtime",
                "nomos.agents", "nomos.ext")
    ruins = [m for m in usados if any(m == p or m.startswith(p + ".") for p in prefixos)]
    assert not ruins, ruins


def test_cli_conselho_module_does_not_touch_filesystem_or_env():
    src = _fonte()
    assert "environ" not in src
    assert "getenv" not in src
    assert "open(" not in src
    assert "write_text" not in src
    assert "write_bytes" not in src


def test_cli_conselho_module_does_not_use_time_or_random():
    # Não importa time/random/secrets nem usa suas APIs (o texto do docstring
    # pode citar as palavras; o que importa é não haver import nem chamada).
    usados = _imports()
    assert "time" not in usados
    assert "random" not in usados
    assert "secrets" not in usados
    src = _fonte()
    assert ".now(" not in src
    assert "random." not in src
    assert "time." not in src


def test_cli_conselho_module_has_no_enable_api():
    # Não existe FUNÇÃO pública que ligue a CLI (enable/activate/unlock/set_*).
    # A constante `MOTOR_COUNCIL_CLI_ENABLED` (um bool literal) não conta — o
    # que se proíbe é uma via executável de habilitação.
    callables = [n for n in dir(cli_disabled)
                 if not n.startswith("_") and callable(getattr(cli_disabled, n))]
    proibidos = [n for n in callables
                 if any(p in n.lower() for p in ("enable", "activate", "unlock",
                                                 "ativar", "habilit"))]
    assert not proibidos, proibidos
    assert cli_disabled.MOTOR_COUNCIL_CLI_ENABLED is False
