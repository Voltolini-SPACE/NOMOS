"""MC16-UX — `/conselho` (chat command) nasce DESABILITADO (fail-closed).

Prova de comportamento do handler puro `handle_disabled_chat_command`: detecta
`/conselho` e subcomandos, devolve a mensagem de bloqueio, nunca ecoa o texto
do usuário, ignora flags proibidas, e devolve `None` para mensagens não
relacionadas — sem chamar orquestrador/harness/policy/vault/audit, sem env.
Prova de pureza (AST) do módulo `nomos.council.chat_disabled`. Mais um teste de
integração pelo chat amigável (`/conselho` responde bloqueado no loop real).
"""
import ast

from nomos.council import chat_disabled

_SENSIVEL = "PROMPT-SENSIVEL-chat-987-nao-pode-vazar"


def _resp(msg):
    return chat_disabled.handle_disabled_chat_command(msg)


# --------------------------------------------------------------------------
# Comportamento do handler
# --------------------------------------------------------------------------

def test_chat_conselho_disabled_root():
    out = _resp("/conselho")
    assert chat_disabled.CHAT_DISABLED_CODE in out
    assert "não está habilitado" in out


def test_chat_conselho_simular_disabled():
    out = _resp(f"/conselho simular {_SENSIVEL}")
    assert chat_disabled.CHAT_DISABLED_CODE in out
    assert _SENSIVEL not in out


def test_chat_conselho_perguntar_disabled():
    out = _resp(f"/conselho perguntar {_SENSIVEL}")
    assert chat_disabled.CHAT_DISABLED_CODE in out
    assert _SENSIVEL not in out


def test_chat_conselho_revisar_disabled():
    out = _resp("/conselho revisar arquivo.md")
    assert chat_disabled.CHAT_DISABLED_CODE in out


def test_chat_conselho_status_disabled():
    out = _resp("/conselho status")
    assert chat_disabled.CHAT_DISABLED_CODE in out
    assert "CHAT_ENABLED=false" in out


def test_chat_conselho_modos_disabled():
    out = _resp("/conselho modos")
    assert chat_disabled.CHAT_DISABLED_CODE in out


def test_chat_conselho_unknown_disabled():
    out = _resp(f"/conselho frobnicate {_SENSIVEL}")
    assert chat_disabled.CHAT_DISABLED_CODE in out
    assert _SENSIVEL not in out


def test_chat_conselho_does_not_echo_prompt():
    for msg in (f"/conselho {_SENSIVEL}",
                f"/conselho simular {_SENSIVEL}",
                f"/conselho perguntar {_SENSIVEL} --cloud"):
        out = _resp(msg)
        assert _SENSIVEL not in out
        assert "SENSIVEL" not in out


def test_chat_conselho_forbidden_flags_do_not_enable():
    for flag in ("--real", "--enable", "--ativar", "--force", "--unsafe",
                 "--cloud", "--audit-real", "--policy-real"):
        out = _resp(f"/conselho simular {_SENSIVEL} {flag}")
        assert chat_disabled.CHAT_DISABLED_CODE in out, flag
        assert "CHAT_ENABLED=false" in out, flag
        assert _SENSIVEL not in out, flag
        assert flag not in out, flag


def test_chat_conselho_output_declares_no_real_execution():
    out = _resp("/conselho")
    for marca in ("CHAT_ENABLED=false", "REAL_ENGINE_EXECUTION=false",
                  "REAL_POLICY=false", "REAL_AUDIT=false", "REAL_VAULT=false",
                  "PERSISTENCE=false"):
        assert marca in out, marca


def test_chat_conselho_no_env_enable(monkeypatch):
    for var in ("MOTOR_COUNCIL_CHAT_ENABLED", "NOMOS_COUNCIL_CHAT_ENABLE",
                "NOMOS_MC_CHAT_ENABLED"):
        monkeypatch.setenv(var, "1")
    out = _resp("/conselho")
    assert "CHAT_ENABLED=false" in out
    assert chat_disabled.MOTOR_COUNCIL_CHAT_ENABLED is False


def test_chat_conselho_does_not_call_orchestrator(monkeypatch):
    import nomos.council.orchestrator as orch

    def boom(*a, **k):
        raise AssertionError("orquestrador não pode ser chamado pelo chat desabilitado")

    monkeypatch.setattr(orch.CouncilOrchestratorDryRun, "run", boom)
    out = _resp(f"/conselho simular {_SENSIVEL}")
    assert chat_disabled.CHAT_DISABLED_CODE in out


def test_chat_conselho_does_not_call_harness(monkeypatch):
    import nomos.council.local_harness as harness

    def boom(*a, **k):
        raise AssertionError("harness real não pode ser chamado pelo chat desabilitado")

    monkeypatch.setattr(harness.LocalExecutionHarness, "execute", boom)
    out = _resp(f"/conselho simular {_SENSIVEL}")
    assert chat_disabled.CHAT_DISABLED_CODE in out


def test_chat_conselho_does_not_call_policy_vault_audit(monkeypatch):
    # O handler é puro: não importa nem toca policy/vault/audit reais. Se
    # tentasse construir o kernel, os patches abaixo explodiriam.
    import nomos.kernel.vault as vault
    import nomos.kernel.policy as policy
    import nomos.kernel.audit as audit

    monkeypatch.setattr(vault, "Vault",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("Vault não pode ser construído")))
    monkeypatch.setattr(policy, "PolicyEngine",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("PolicyEngine não pode ser construído")))
    monkeypatch.setattr(audit, "AuditLog",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("AuditLog não pode ser construído")))
    out = _resp(f"/conselho simular {_SENSIVEL}")
    assert chat_disabled.CHAT_DISABLED_CODE in out


def test_chat_conselho_non_command_ignored():
    for msg in ("oi tudo bem?", "/ajuda", "/conselhoxyz", "conselho sem barra",
                "", "   ", 42, None):
        assert chat_disabled.handle_disabled_chat_command(msg) is None


def test_chat_conselho_no_enable_api():
    callables = [n for n in dir(chat_disabled)
                 if not n.startswith("_") and callable(getattr(chat_disabled, n))]
    proibidos = [n for n in callables
                 if any(p in n.lower() for p in ("enable", "activate", "unlock",
                                                 "ativar", "habilit"))]
    assert not proibidos, proibidos
    assert chat_disabled.MOTOR_COUNCIL_CHAT_ENABLED is False


# --------------------------------------------------------------------------
# Integração pelo chat amigável (loop real)
# --------------------------------------------------------------------------

def test_chat_conselho_disabled_via_amigavel(tmp_path):
    from nomos.kernel.policy import PolicyEngine
    from nomos.simple import amigavel

    feed = iter(["/conselho simular " + _SENSIVEL, "/sair"])
    tela = []
    ctx = {"home": tmp_path, "policy": PolicyEngine(tmp_path / "p.json")}
    amigavel.iniciar_chat(ctx, {"agent_name": "Luna", "modo_cerebro": "demo"},
                          router=None, ask=lambda _: next(feed), say=tela.append,
                          colorido=False, aprovador=lambda d: True)
    saida = "\n".join(str(x) for x in tela)
    assert chat_disabled.CHAT_DISABLED_CODE in saida
    assert _SENSIVEL not in saida


# --------------------------------------------------------------------------
# Pureza / segurança por AST
# --------------------------------------------------------------------------

def _imports():
    src = open(chat_disabled.__file__, encoding="utf-8").read()
    nomes = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            nomes.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            nomes.add(node.module)
    return nomes


def _fonte():
    return open(chat_disabled.__file__, encoding="utf-8").read()


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


def test_chat_conselho_module_does_not_import_council_or_kernel_runtime():
    # Não importa orquestrador/harness nem policy/vault/audit reais.
    usados = _imports()
    prefixos = ("nomos.council.orchestrator", "nomos.council.local_harness",
                "nomos.council.policy_gate", "nomos.council.audit_envelope",
                "nomos.kernel", "nomos.cognition", "nomos.runtime",
                "nomos.agents", "nomos.ext")
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
