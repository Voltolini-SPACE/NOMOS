"""MC15-UX — `nomos conselho simular` (dry-run) e o resto ainda fail-closed.

Prova que apenas `simular` sai do esqueleto desabilitado, chamando só o
`CouncilOrchestratorDryRun`; que o prompt nunca é ecoado (humano/JSON/erro);
que o orquestrador/harness/policy/vault/audit reais não são chamados e `_paths()`
não é construído; que as flags proibidas falham fechado; e que o módulo novo é
puro (AST).
"""
import ast
import io

import pytest

from nomos import cli
from nomos.council import cli_dry_run

_SENSIVEL = "PROMPT-SENSIVEL-xyz789-nao-pode-vazar"


@pytest.fixture(autouse=True)
def _nao_interativo(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    yield


def _run(capsys, *argv):
    rc = cli.main(list(argv))
    out = capsys.readouterr().out
    return rc, out


# --------------------------------------------------------------------------
# `simular` — caminho dry-run permitido
# --------------------------------------------------------------------------

def test_cli_conselho_simular_dry_run_allowed(capsys):
    rc, out = _run(capsys, "conselho", "simular", "uma pergunta qualquer")
    assert cli_dry_run.DRY_RUN_CODE in out
    assert rc == cli_dry_run.DRY_RUN_EXIT_CODE


def test_cli_conselho_simular_outputs_dry_run_flags(capsys):
    rc, out = _run(capsys, "conselho", "simular", "texto")
    for marca in ("DRY_RUN=true", "REAL_ENGINE_EXECUTION=false",
                  "REAL_POLICY=false", "REAL_AUDIT=false", "REAL_VAULT=false",
                  "PERSISTENCE=false"):
        assert marca in out, marca


def test_cli_conselho_simular_json_redacted(capsys):
    rc, out = _run(capsys, "conselho", "simular", _SENSIVEL, "--json")
    assert _SENSIVEL not in out
    import json as _json
    payload = _json.loads(out.strip())
    assert payload["dry_run"] is True
    assert payload["allowed"] is True
    assert payload["would_execute"] is False
    assert payload["would_write_audit"] is False
    assert payload["persist_allowed"] is True
    assert payload["private_mode"] is False


def test_cli_conselho_simular_private_json_persist_false(capsys):
    rc, out = _run(capsys, "conselho", "simular", "texto", "--privado", "--json")
    import json as _json
    payload = _json.loads(out.strip())
    assert payload["private_mode"] is True
    assert payload["persist_allowed"] is False
    assert payload["dry_run"] is True
    assert payload["would_execute"] is False
    assert payload["would_write_audit"] is False


def test_cli_conselho_simular_does_not_echo_prompt(capsys):
    rc, out = _run(capsys, "conselho", "simular", _SENSIVEL)
    assert _SENSIVEL not in out
    assert "SENSIVEL" not in out
    rc2, out2 = _run(capsys, "conselho", "simular", _SENSIVEL, "--json")
    assert _SENSIVEL not in out2


def test_cli_conselho_simular_mode_balanceado_default(capsys):
    # sem --modo => balanceado => permitido
    rc, out = _run(capsys, "conselho", "simular", "texto", "--json")
    import json as _json
    payload = _json.loads(out.strip())
    assert payload["allowed"] is True
    assert payload["private_mode"] is False


def test_cli_conselho_simular_mode_paranoico_private(capsys):
    rc, out = _run(capsys, "conselho", "simular", "texto", "--modo", "paranoico", "--json")
    import json as _json
    payload = _json.loads(out.strip())
    assert payload["private_mode"] is True
    assert payload["persist_allowed"] is False


def test_cli_conselho_simular_invalid_mode_fails_closed(capsys):
    rc, out = _run(capsys, "conselho", "simular", "texto", "--modo", "INVALIDO-SECRETO")
    assert cli_dry_run.DENIED_CODE in out
    assert "INVALIDO-SECRETO" not in out
    assert rc == cli_dry_run.DENIED_EXIT_CODE


def test_cli_conselho_simular_gate_blocked_hides_content(capsys, monkeypatch):
    # Simula um resultado bloqueado pelo gate e confirma que a CLI esconde
    # qualquer conteúdo e imprime a mensagem de gate.
    from nomos.council import orchestrator as orch

    class _Blocked:
        allowed = False
        blocked = True
        failure_code = orch.OrchestrationFailureCode.ORCH_POLICY_GATE_DENIED

    monkeypatch.setattr(orch.CouncilOrchestratorDryRun, "run",
                        lambda self, entrada: _Blocked())
    rc, out = _run(capsys, "conselho", "simular", _SENSIVEL)
    assert cli_dry_run.GATE_BLOCKED_CODE in out
    assert "não será exibido" in out
    assert _SENSIVEL not in out


def test_cli_conselho_simular_sensitive_data_blocks_or_redacts(capsys, monkeypatch):
    # Se o orquestrador bloquear por dado sensível, a CLI não vaza nada.
    from nomos.council import orchestrator as orch

    class _Blocked:
        allowed = False
        blocked = True
        failure_code = orch.OrchestrationFailureCode.ORCH_POLICY_GATE_DENIED

    monkeypatch.setattr(orch.CouncilOrchestratorDryRun, "run",
                        lambda self, entrada: _Blocked())
    rc, out = _run(capsys, "conselho", "simular", _SENSIVEL, "--json")
    assert _SENSIVEL not in out
    import json as _json
    payload = _json.loads(out.strip())
    assert payload["allowed"] is False
    assert payload["blocked"] is True
    assert payload["would_execute"] is False


# --------------------------------------------------------------------------
# Demais comandos continuam DESABILITADOS
# --------------------------------------------------------------------------

def test_cli_conselho_root_still_disabled(capsys):
    rc, out = _run(capsys, "conselho")
    assert "[NOMOS-MC-CLI-DISABLED]" in out


def test_cli_conselho_perguntar_still_disabled(capsys):
    rc, out = _run(capsys, "conselho", "perguntar", _SENSIVEL)
    assert "[NOMOS-MC-CLI-DISABLED]" in out
    assert _SENSIVEL not in out


def test_cli_conselho_revisar_still_disabled(capsys):
    rc, out = _run(capsys, "conselho", "revisar", "arquivo.md")
    assert "[NOMOS-MC-CLI-DISABLED]" in out


def test_cli_conselho_status_still_disabled(capsys):
    rc, out = _run(capsys, "conselho", "status")
    assert "[NOMOS-MC-CLI-DISABLED]" in out


def test_cli_conselho_modos_still_disabled(capsys):
    rc, out = _run(capsys, "conselho", "modos")
    assert "[NOMOS-MC-CLI-DISABLED]" in out


def test_cli_conselho_unknown_still_disabled(capsys):
    rc, out = _run(capsys, "conselho", "frobnicate", _SENSIVEL)
    assert "[NOMOS-MC-CLI-DISABLED]" in out
    assert _SENSIVEL not in out


# --------------------------------------------------------------------------
# Flags proibidas e não-chamada de camadas reais
# --------------------------------------------------------------------------

def test_cli_conselho_forbidden_flags_do_not_enable_real_execution(capsys):
    for flag in ("--real", "--enable", "--ativar", "--force", "--unsafe",
                 "--cloud", "--audit-real", "--policy-real"):
        rc, out = _run(capsys, "conselho", "simular", _SENSIVEL, flag)
        assert cli_dry_run.DENIED_CODE in out, flag
        assert _SENSIVEL not in out, flag
        assert rc == cli_dry_run.DENIED_EXIT_CODE, flag


def test_cli_conselho_does_not_call_harness_execute(capsys, monkeypatch):
    import nomos.council.local_harness as harness

    def boom(*a, **k):
        raise AssertionError("harness real não pode ser chamado")

    monkeypatch.setattr(harness.LocalExecutionHarness, "execute", boom)
    rc, out = _run(capsys, "conselho", "simular", "texto")
    assert cli_dry_run.DRY_RUN_CODE in out


def test_cli_conselho_does_not_call_policy_vault_audit(capsys, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("_paths (vault/policy/audit) não pode ser construído")

    monkeypatch.setattr(cli, "_paths", boom)
    rc, out = _run(capsys, "conselho", "simular", "texto")
    assert cli_dry_run.DRY_RUN_CODE in out


def test_cli_conselho_does_not_construct_paths_for_simular(capsys, monkeypatch):
    chamadas = {"n": 0}

    def contar(*a, **k):
        chamadas["n"] += 1
        raise AssertionError("_paths não deve ser chamado por simular")

    monkeypatch.setattr(cli, "_paths", contar)
    rc, out = _run(capsys, "conselho", "simular", "texto", "--json")
    assert chamadas["n"] == 0
    assert '"dry_run": true' in out


def test_cli_conselho_json_has_no_prompt_or_content_keys(capsys):
    rc, out = _run(capsys, "conselho", "simular", _SENSIVEL, "--json")
    for chave in ("prompt", "content", "final_content", "candidate_content",
                  "engine_id", "secret", "token", "api_key"):
        assert chave not in out, chave


def test_cli_conselho_help_mentions_dry_run_and_disabled(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out.lower()
    assert "conselho" in out
    assert "dry-run" in out or "dry run" in out
    assert "desabilitad" in out or "disabled" in out


def test_cli_conselho_orchestrator_exception_fails_closed(capsys, monkeypatch):
    from nomos.council import orchestrator as orch

    def boom(self, entrada):
        raise RuntimeError("falha interna simulada")

    monkeypatch.setattr(orch.CouncilOrchestratorDryRun, "run", boom)
    rc, out = _run(capsys, "conselho", "simular", _SENSIVEL)
    assert cli_dry_run.BLOCKED_CODE in out
    assert _SENSIVEL not in out
    assert "Traceback" not in out
    assert rc == cli_dry_run.DENIED_EXIT_CODE


# --------------------------------------------------------------------------
# Pureza / segurança por AST do módulo cli_dry_run
# --------------------------------------------------------------------------

def _imports():
    src = open(cli_dry_run.__file__, encoding="utf-8").read()
    nomes = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            nomes.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            nomes.add(node.module)
    return nomes


def _fonte():
    return open(cli_dry_run.__file__, encoding="utf-8").read()


def test_cli_conselho_dry_run_module_does_not_import_network():
    proibidos = {"socket", "ssl", "http", "http.client", "urllib",
                 "urllib.request", "requests", "httpx", "aiohttp", "ftplib",
                 "smtplib"}
    assert not (_imports() & proibidos), _imports() & proibidos


def test_cli_conselho_dry_run_module_does_not_import_subprocess_threading_asyncio():
    proibidos = {"subprocess", "threading", "multiprocessing", "asyncio",
                 "concurrent.futures", "signal"}
    assert not (_imports() & proibidos), _imports() & proibidos


def test_cli_conselho_dry_run_module_does_not_import_cloud_clients():
    usados = _imports()
    prefixos = ("openai", "anthropic", "google", "google.generativeai", "gemini",
                "cohere", "boto3", "azure", "vertexai", "ollama", "llama_cpp",
                "transformers", "torch")
    ruins = [m for m in usados if any(m == p or m.startswith(p + ".") for p in prefixos)]
    assert not ruins, ruins


def test_cli_conselho_dry_run_module_does_not_import_real_kernel_or_harness():
    # Pode importar o orquestrador dry-run; NÃO pode importar harness real nem
    # policy/audit/vault reais do kernel, nem router/motores.
    usados = _imports()
    prefixos = ("nomos.council.local_harness", "nomos.kernel.policy",
                "nomos.kernel.vault", "nomos.kernel.audit", "nomos.kernel",
                "nomos.cognition", "nomos.runtime", "nomos.agents", "nomos.ext")
    ruins = [m for m in usados if any(m == p or m.startswith(p + ".") for p in prefixos)]
    assert not ruins, ruins


def test_cli_conselho_dry_run_module_does_not_touch_filesystem_or_env():
    src = _fonte()
    assert "environ" not in src
    assert "getenv" not in src
    assert "open(" not in src
    assert "write_text" not in src
    assert "write_bytes" not in src


def test_cli_conselho_dry_run_module_does_not_use_time_or_random():
    usados = _imports()
    assert "time" not in usados
    assert "random" not in usados
    assert "secrets" not in usados
    src = _fonte()
    assert ".now(" not in src
    assert "random." not in src
    assert "time." not in src
