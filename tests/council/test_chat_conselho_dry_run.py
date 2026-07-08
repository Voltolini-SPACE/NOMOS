"""MC18-UX — `/conselho simular` (chat dry-run) e o resto ainda fail-closed.

Prova que só `simular` sai do esqueleto desabilitado do chat, chamando apenas o
`CouncilOrchestratorDryRun`; que o prompt nunca é ecoado (humano/JSON); que o
harness/policy/vault/audit reais não são chamados; que o JSON é montado à mão
(nunca `result.to_dict()`); que as flags proibidas falham fechado; e que o
módulo novo é puro (AST). Inclui integração pelo loop real do chat amigável.
"""
import ast
import json

from nomos.council import chat_dry_run

_SENSIVEL = "PROMPT-SENSIVEL-chatdr-555-nao-pode-vazar"


def _h(msg):
    return chat_dry_run.handle_chat_dry_run(msg)


# --------------------------------------------------------------------------
# `simular` — caminho dry-run permitido
# --------------------------------------------------------------------------

def test_chat_conselho_simular_dry_run_allowed():
    out = _h("/conselho simular uma pergunta qualquer")
    assert chat_dry_run.DRY_RUN_CODE in out


def test_chat_conselho_simular_outputs_dry_run_flags():
    out = _h("/conselho simular texto")
    for marca in ("DRY_RUN=true", "REAL_ENGINE_EXECUTION=false",
                  "REAL_POLICY=false", "REAL_AUDIT=false", "REAL_VAULT=false",
                  "PERSISTENCE=false"):
        assert marca in out, marca


def test_chat_conselho_simular_json_redacted_if_supported():
    out = _h(f"/conselho simular {_SENSIVEL} --json")
    assert _SENSIVEL not in out
    payload = json.loads(out)
    assert payload["dry_run"] is True
    assert payload["allowed"] is True
    assert payload["would_execute"] is False
    assert payload["would_write_audit"] is False
    assert payload["persist_allowed"] is True
    assert payload["private_mode"] is False


def test_chat_conselho_simular_private_no_persist():
    out = _h("/conselho simular texto --privado --json")
    payload = json.loads(out)
    assert payload["private_mode"] is True
    assert payload["persist_allowed"] is False


def test_chat_conselho_simular_paranoico_private():
    out = _h("/conselho simular texto --modo paranoico --json")
    payload = json.loads(out)
    assert payload["private_mode"] is True
    assert payload["persist_allowed"] is False


def test_chat_conselho_simular_does_not_echo_prompt():
    assert _SENSIVEL not in _h(f"/conselho simular {_SENSIVEL}")
    assert _SENSIVEL not in _h(f"/conselho simular {_SENSIVEL} --json")


def test_chat_conselho_simular_default_mode_balanceado():
    out = _h("/conselho simular texto --json")
    payload = json.loads(out)
    assert payload["allowed"] is True
    assert payload["private_mode"] is False


def test_chat_conselho_simular_invalid_mode_denied():
    out = _h("/conselho simular texto --modo INVALIDO-SECRETO")
    assert chat_dry_run.DENIED_CODE in out
    assert "INVALIDO-SECRETO" not in out


def test_chat_conselho_simular_gate_blocked_hides_content(monkeypatch):
    from nomos.council import orchestrator as orch

    class _Blocked:
        allowed = False
        blocked = True
        failure_code = orch.OrchestrationFailureCode.ORCH_POLICY_GATE_DENIED

    monkeypatch.setattr(orch.CouncilOrchestratorDryRun, "run",
                        lambda self, entrada: _Blocked())
    out = _h(f"/conselho simular {_SENSIVEL}")
    assert chat_dry_run.GATE_BLOCKED_CODE in out
    assert "não será exibido" in out
    assert _SENSIVEL not in out


def test_chat_conselho_simular_sensitive_data_blocks_or_redacts(monkeypatch):
    from nomos.council import orchestrator as orch

    class _Blocked:
        allowed = False
        blocked = True
        failure_code = orch.OrchestrationFailureCode.ORCH_POLICY_GATE_DENIED

    monkeypatch.setattr(orch.CouncilOrchestratorDryRun, "run",
                        lambda self, entrada: _Blocked())
    out = _h(f"/conselho simular {_SENSIVEL} --json")
    assert _SENSIVEL not in out
    payload = json.loads(out)
    assert payload["allowed"] is False
    assert payload["blocked"] is True
    assert payload["would_execute"] is False


# --------------------------------------------------------------------------
# Demais comandos continuam DESABILITADOS
# --------------------------------------------------------------------------

def test_chat_conselho_root_still_disabled():
    assert "[NOMOS-MC-CHAT-DISABLED]" in _h("/conselho")


def test_chat_conselho_perguntar_still_disabled():
    out = _h(f"/conselho perguntar {_SENSIVEL}")
    assert "[NOMOS-MC-CHAT-DISABLED]" in out
    assert _SENSIVEL not in out


def test_chat_conselho_revisar_still_disabled():
    assert "[NOMOS-MC-CHAT-DISABLED]" in _h("/conselho revisar arquivo.md")


def test_chat_conselho_status_now_informational():
    # MC24-UX: `/conselho status` finalizado como informativo puro no chat.
    out = _h("/conselho status")
    assert "[NOMOS-MC-STATUS]" in out
    assert "REAL_ENGINE_EXECUTION=false" in out
    assert "[NOMOS-MC-CHAT-DISABLED]" not in out


def test_chat_conselho_modos_now_informational():
    out = _h("/conselho modos")
    assert "[NOMOS-MC-MODOS]" in out
    for modo in ("rapido", "balanceado", "critico", "paranoico"):
        assert modo in out, modo
    assert "[NOMOS-MC-CHAT-DISABLED]" not in out


def test_chat_conselho_modos_avancado():
    out = _h("/conselho modos --avancado")
    assert "CouncilMode" in out and "balanceado=balanced" in out


def test_chat_conselho_info_recusa_flag_proibida_sem_ecoar():
    # defesa em profundidade: nenhuma flag "liga" nada nem é ecoada
    for flag in ("--real", "--enable", "--cloud", "--engine-real", "--vault-real"):
        out = _h(f"/conselho status {flag}")
        assert chat_dry_run.DENIED_CODE in out, flag
        assert flag not in out, flag


def test_chat_conselho_unknown_still_disabled():
    out = _h(f"/conselho frobnicate {_SENSIVEL}")
    assert "[NOMOS-MC-CHAT-DISABLED]" in out
    assert _SENSIVEL not in out


# --------------------------------------------------------------------------
# Flags proibidas, não-comando, camadas reais
# --------------------------------------------------------------------------

def test_chat_conselho_forbidden_flags_denied():
    for flag in ("--real", "--enable", "--ativar", "--force", "--unsafe",
                 "--cloud", "--audit-real", "--policy-real", "--vault-real",
                 "--engine-real"):
        out = _h(f"/conselho simular {_SENSIVEL} {flag}")
        assert chat_dry_run.DENIED_CODE in out, flag
        assert _SENSIVEL not in out, flag
        assert flag not in out, flag


def test_chat_conselho_non_command_still_ignored():
    for msg in ("oi tudo bem?", "/ajuda", "/conselhoxyz", "conselho sem barra",
                "", "   ", 42, None):
        assert chat_dry_run.handle_chat_dry_run(msg) is None


def test_chat_conselho_does_not_call_harness_execute(monkeypatch):
    import nomos.council.local_harness as harness

    def boom(*a, **k):
        raise AssertionError("harness real não pode ser chamado")

    monkeypatch.setattr(harness.LocalExecutionHarness, "execute", boom)
    out = _h("/conselho simular texto")
    assert chat_dry_run.DRY_RUN_CODE in out


def test_chat_conselho_does_not_call_policy_vault_audit(monkeypatch):
    import nomos.kernel.audit as audit
    import nomos.kernel.policy as policy
    import nomos.kernel.vault as vault

    def boom(*a, **k):
        raise AssertionError("kernel real (vault/policy/audit) não pode ser construído")

    monkeypatch.setattr(vault, "Vault", boom)
    monkeypatch.setattr(policy, "PolicyEngine", boom)
    monkeypatch.setattr(audit, "AuditLog", boom)
    out = _h(f"/conselho simular {_SENSIVEL}")
    assert chat_dry_run.DRY_RUN_CODE in out


def test_chat_conselho_does_not_use_result_to_dict(monkeypatch):
    # Se a CLI/chat chamasse result.to_dict(), este patch explodiria.
    from nomos.council import orchestrator as orch

    def boom(self):
        raise AssertionError("result.to_dict() não pode ser usado pelo chat dry-run")

    monkeypatch.setattr(orch.CouncilOrchestrationResult, "to_dict", boom)
    out = _h(f"/conselho simular {_SENSIVEL} --json")
    payload = json.loads(out)
    assert payload["dry_run"] is True


def test_chat_conselho_json_has_no_prompt_or_content_keys():
    out = _h(f"/conselho simular {_SENSIVEL} --json")
    for chave in ("prompt", "content", "final_content", "candidate_content",
                  "engine_id", "secret", "token", "api_key", "authorization",
                  "bearer"):
        assert chave not in out, chave


def test_chat_conselho_human_output_has_no_prompt_or_content():
    out = _h(f"/conselho simular {_SENSIVEL}")
    assert _SENSIVEL not in out
    for chave in ("engine_id", "candidate_content", "final_content"):
        assert chave not in out, chave


def test_chat_conselho_orchestrator_exception_fails_closed(monkeypatch):
    from nomos.council import orchestrator as orch

    def boom(self, entrada):
        raise RuntimeError("falha interna simulada")

    monkeypatch.setattr(orch.CouncilOrchestratorDryRun, "run", boom)
    out = _h(f"/conselho simular {_SENSIVEL}")
    assert chat_dry_run.BLOCKED_CODE in out
    assert _SENSIVEL not in out
    assert "Traceback" not in out


# --------------------------------------------------------------------------
# Integração pelo chat amigável (loop real)
# --------------------------------------------------------------------------

def _chat(entradas, tmp_path):
    from nomos.kernel.policy import PolicyEngine
    from nomos.simple import amigavel

    feed = iter(entradas)
    tela = []
    ctx = {"home": tmp_path, "policy": PolicyEngine(tmp_path / "p.json")}
    amigavel.iniciar_chat(ctx, {"agent_name": "Luna", "modo_cerebro": "demo"},
                          router=None, ask=lambda _: next(feed), say=tela.append,
                          colorido=False, aprovador=lambda d: True)
    return "\n".join(str(x) for x in tela)


def test_chat_conselho_amigavel_integration_dry_run(tmp_path):
    saida = _chat(["/conselho simular " + _SENSIVEL, "/sair"], tmp_path)
    assert chat_dry_run.DRY_RUN_CODE in saida
    assert _SENSIVEL not in saida


def test_chat_ajuda_mentions_conselho_simular_dry_run(tmp_path):
    # MC19: o /ajuda do chat deve refletir que `/conselho simular` roda dry-run.
    saida = _chat(["/ajuda", "/sair"], tmp_path).lower()
    assert "/conselho simular" in saida
    assert "dry-run" in saida


def test_cli_help_mentions_conselho_simular_dry_run(capsys):
    # MC19: o `nomos --help` deve indicar que `conselho simular` roda dry-run.
    import pytest as _pytest

    from nomos import cli
    with _pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out.lower()
    assert "conselho" in out
    assert "simular" in out
    assert "dry-run" in out


def test_chat_conselho_amigavel_integration_disabled_routes(tmp_path):
    saida = _chat(["/conselho perguntar " + _SENSIVEL, "/sair"], tmp_path)
    assert "[NOMOS-MC-CHAT-DISABLED]" in saida
    assert _SENSIVEL not in saida


# --------------------------------------------------------------------------
# Pureza / segurança por AST
# --------------------------------------------------------------------------

def _imports():
    src = open(chat_dry_run.__file__, encoding="utf-8").read()
    nomes = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            nomes.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            nomes.add(node.module)
    return nomes


def _fonte():
    return open(chat_dry_run.__file__, encoding="utf-8").read()


def test_chat_conselho_module_does_not_import_network():
    proibidos = {"socket", "ssl", "http", "http.client", "urllib",
                 "urllib.request", "requests", "httpx", "aiohttp", "ftplib",
                 "smtplib"}
    assert not (_imports() & proibidos), _imports() & proibidos


def test_chat_conselho_module_does_not_import_subprocess_threading_asyncio():
    proibidos = {"subprocess", "threading", "multiprocessing", "asyncio",
                 "concurrent.futures", "signal"}
    assert not (_imports() & proibidos), _imports() & proibidos


def test_chat_conselho_module_does_not_import_cloud_clients():
    usados = _imports()
    prefixos = ("openai", "anthropic", "google", "google.generativeai", "gemini",
                "cohere", "boto3", "azure", "vertexai", "ollama", "llama_cpp",
                "transformers", "torch")
    ruins = [m for m in usados if any(m == p or m.startswith(p + ".") for p in prefixos)]
    assert not ruins, ruins


def test_chat_conselho_module_does_not_touch_filesystem_or_env():
    src = _fonte()
    assert "environ" not in src
    assert "getenv" not in src
    assert "open(" not in src
    assert "write_text" not in src
    assert "write_bytes" not in src


def test_chat_conselho_module_does_not_use_time_or_random():
    usados = _imports()
    assert "time" not in usados
    assert "random" not in usados
    assert "secrets" not in usados
    src = _fonte()
    assert ".now(" not in src
    assert "random." not in src
    assert "time." not in src


def test_chat_conselho_module_does_not_import_harness_policy_vault_audit():
    # Pode importar o orquestrador dry-run e chat_disabled; NÃO pode importar
    # harness real nem policy/audit/vault reais do kernel, nem router/motores.
    usados = _imports()
    prefixos = ("nomos.council.local_harness", "nomos.kernel.policy",
                "nomos.kernel.vault", "nomos.kernel.audit", "nomos.kernel",
                "nomos.cognition", "nomos.runtime", "nomos.agents", "nomos.ext")
    ruins = [m for m in usados if any(m == p or m.startswith(p + ".") for p in prefixos)]
    assert not ruins, ruins


def test_chat_conselho_module_does_not_use_result_to_dict_in_source():
    assert "to_dict" not in _fonte()


# --------------------------------------------------------------------------
# MC23 — migração ao helper compartilhado + UX simples
# --------------------------------------------------------------------------

_JARGAO = ("orchestrator", "orquestrador", "envelope", "scalar", "payload",
           "safe output", "safe_output", "policy dry-run", "failure_code",
           "to_dict", "CouncilSafeOutput")


def test_chat_conselho_uses_safe_output_helper(monkeypatch):
    chamadas = {"n": 0}
    real = chat_dry_run.build_safe_output

    def _spy(*a, **k):
        chamadas["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(chat_dry_run, "build_safe_output", _spy)
    _h("/conselho simular uma pergunta")
    assert chamadas["n"] == 1


def test_chat_conselho_module_imports_safe_output_helper():
    assert "nomos.council.safe_output" in _imports()


def test_chat_conselho_json_uses_safe_output_shape():
    payload = json.loads(_h("/conselho simular texto --json"))
    assert set(payload.keys()) == {
        "interface", "dry_run", "allowed", "blocked", "would_execute",
        "would_write_audit", "private_mode", "persist_allowed", "failure_code",
        "mode",
    }


def test_chat_conselho_json_contains_interface_and_mode():
    payload = json.loads(_h("/conselho simular texto --modo critico --json"))
    assert payload["interface"] == "chat"
    assert payload["mode"] == "critical"


def test_chat_conselho_default_mode_json_balanced():
    payload = json.loads(_h("/conselho simular texto --json"))
    assert payload["mode"] == "balanced"


def test_chat_conselho_human_output_is_user_friendly():
    out = _h("/conselho simular texto")
    assert "Simulação segura concluída." in out
    assert "Nada foi executado de verdade." in out
    assert "Nada foi salvo." in out
    assert "Nenhum dado sensível foi exibido." in out


def test_chat_conselho_human_output_avoids_internal_jargon():
    baixo = _h("/conselho simular texto").lower()
    for termo in _JARGAO:
        assert termo.lower() not in baixo, termo


def test_chat_conselho_prompt_still_not_echoed_after_migration():
    assert _SENSIVEL not in _h(f"/conselho simular {_SENSIVEL}")
    assert _SENSIVEL not in _h(f"/conselho simular {_SENSIVEL} --json")


def test_chat_conselho_gate_blocked_safe_after_migration(monkeypatch):
    from nomos.council import orchestrator as orch

    class _Blocked:
        allowed = False
        blocked = True
        failure_code = orch.OrchestrationFailureCode.ORCH_POLICY_GATE_DENIED

    monkeypatch.setattr(orch.CouncilOrchestratorDryRun, "run",
                        lambda self, entrada: _Blocked())
    out = _h(f"/conselho simular {_SENSIVEL}")
    assert chat_dry_run.GATE_BLOCKED_CODE in out
    assert "bloqueada por segurança" in out
    assert _SENSIVEL not in out


def test_chat_conselho_denied_safe_after_migration():
    out = _h(f"/conselho simular {_SENSIVEL} --vault-real")
    assert chat_dry_run.DENIED_CODE in out
    assert _SENSIVEL not in out
    assert "--vault-real" not in out


def test_chat_conselho_exception_safe_after_migration(monkeypatch):
    from nomos.council import orchestrator as orch

    def boom(self, entrada):
        raise RuntimeError("falha simulada")

    monkeypatch.setattr(orch.CouncilOrchestratorDryRun, "run", boom)
    out = _h(f"/conselho simular {_SENSIVEL}")
    assert chat_dry_run.BLOCKED_CODE in out
    assert _SENSIVEL not in out
    assert "Traceback" not in out


def test_chat_conselho_non_command_still_returns_none_after_migration():
    for msg in ("oi", "/ajuda", "/conselhoxyz", "", "   ", 42, None):
        assert chat_dry_run.handle_chat_dry_run(msg) is None


def test_chat_conselho_still_no_result_to_dict_after_migration(monkeypatch):
    from nomos.council import orchestrator as orch

    def boom(self):
        raise AssertionError("o chat não pode usar result.to_dict() após a migração")

    monkeypatch.setattr(orch.CouncilOrchestrationResult, "to_dict", boom)
    out = _h("/conselho simular texto --json")
    assert '"dry_run": true' in out


def test_chat_conselho_module_no_result_dump_after_migration():
    src = _fonte()
    assert ".to_dict(" not in src
    assert "repr(" not in src
    assert "vars(" not in src
    assert "asdict" not in src
    assert "json.dumps(result" not in src


def test_cli_dry_run_untouched(capsys):
    # A MC23 migra só o CHAT; o CLI (migrado na MC22) segue funcionando igual,
    # sem ser alterado nesta fase.
    from nomos import cli
    from nomos.council import cli_dry_run
    cli.main(["conselho", "simular", "só para conferir o CLI"])
    out = capsys.readouterr().out
    assert cli_dry_run.DRY_RUN_CODE in out
    assert "Simulação segura concluída." in out
