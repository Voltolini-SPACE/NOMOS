"""MC21 — helper compartilhado de saída segura (`nomos.council.safe_output`).

Prova que o helper isolado só emite escalares permitidos, nunca ecoa
prompt/conteúdo/engine_id/segredos, nunca usa `result.to_dict()`/`repr`/`vars`/
`asdict`, falha fechado para resultado inválido, e é puro (AST). O helper ainda
NÃO é usado pela CLI nem pelo chat (migração é MC22/MC23).
"""
import ast
import dataclasses
import json

import pytest

from nomos.council import safe_output as so

_SAFE_KEYS = {
    "interface", "dry_run", "allowed", "blocked", "would_execute",
    "would_write_audit", "private_mode", "persist_allowed", "failure_code",
    "mode",
}

_FORBIDDEN_SUBSTRINGS = (
    "prompt", "content", "final_content", "candidate_content", "engine_id",
    "secret", "token", "api_key", "authorization", "bearer", "trace",
    "audit_envelope", "candidate", "raw_result",
)


class _Result:
    """Resultado dry-run válido de teste."""

    def __init__(self, allowed=True, blocked=None, failure_code=None):
        self.allowed = allowed
        self.blocked = (not allowed) if blocked is None else blocked
        self.failure_code = failure_code


class _EnumFC:
    def __init__(self, value):
        self.value = value


class _Trap:
    """Resultado que explode se alguém tentar serializá-lo indevidamente."""

    allowed = True
    blocked = False
    failure_code = None

    def to_dict(self):
        raise AssertionError("build_safe_output não pode chamar result.to_dict()")

    def __repr__(self):
        raise AssertionError("build_safe_output não pode chamar repr(result)")


def _out(interface="cli", mode="balanced", private_mode=False, **kw):
    return so.build_safe_output(_Result(**kw), interface=interface, mode=mode,
                                private_mode=private_mode)


# --------------------------------------------------------------------------
# Estrutura / JSON
# --------------------------------------------------------------------------

def test_safe_output_dataclass_is_frozen():
    assert so.CouncilSafeOutput.__dataclass_params__.frozen is True
    o = _out()
    with pytest.raises(dataclasses.FrozenInstanceError):
        o.allowed = False  # type: ignore[misc]


def test_safe_output_json_contains_only_safe_keys():
    payload = json.loads(so.render_json_output(_out()))
    assert set(payload.keys()) == _SAFE_KEYS


def test_safe_output_json_cli_interface():
    payload = json.loads(so.render_json_output(_out(interface="cli")))
    assert payload["interface"] == "cli"
    assert payload["dry_run"] is True


def test_safe_output_json_chat_interface():
    payload = json.loads(so.render_json_output(_out(interface="chat")))
    assert payload["interface"] == "chat"


def test_safe_output_private_persist_false():
    payload = json.loads(so.render_json_output(_out(private_mode=True)))
    assert payload["private_mode"] is True
    assert payload["persist_allowed"] is False


def test_safe_output_paranoid_mode_allowed():
    o = _out(mode="paranoid", private_mode=True)
    assert o.mode == "paranoid"
    assert o.persist_allowed is False


def test_safe_output_invalid_interface_rejected():
    with pytest.raises(ValueError):
        so.build_safe_output(_Result(), interface="api", mode="fast",
                             private_mode=False)


def test_safe_output_invalid_mode_rejected():
    with pytest.raises(ValueError):
        so.build_safe_output(_Result(), interface="cli", mode="rapido",
                             private_mode=False)


def test_safe_output_invalid_result_fails_closed():
    o = so.build_safe_output(object(), interface="cli", mode="fast",
                             private_mode=False)
    assert o.allowed is False
    assert o.blocked is True
    assert o.failure_code == so.SAFE_OUTPUT_INVALID_RESULT
    assert o.would_execute is False
    assert o.would_write_audit is False


# --------------------------------------------------------------------------
# Nunca usar to_dict / repr / vars
# --------------------------------------------------------------------------

def test_safe_output_never_calls_result_to_dict():
    o = so.build_safe_output(_Trap(), interface="cli", mode="balanced",
                             private_mode=False)
    assert o.allowed is True
    # renderizações também não podem tocar o result (o output já é escalar)
    so.render_json_output(o)
    so.render_human_output(o)


def test_safe_output_never_calls_result_repr():
    # _Trap.__repr__ explode; se build/render chamassem repr(result) falharia.
    o = so.build_safe_output(_Trap(), interface="chat", mode="fast",
                             private_mode=True)
    assert so.render_human_output(o).startswith(so._CODES["chat"]["dry_run"])


def test_safe_output_never_uses_vars():
    src = open(so.__file__, encoding="utf-8").read()
    assert "vars(" not in src
    assert "asdict" not in src
    assert ".to_dict(" not in src
    assert "repr(" not in src
    assert "json.dumps(result" not in src


# --------------------------------------------------------------------------
# Render humano
# --------------------------------------------------------------------------

def test_safe_output_human_cli_success():
    txt = so.render_human_output(_out(interface="cli"))
    assert "[NOMOS-MC-DRY-RUN]" in txt
    assert "Motor Council simulado com sucesso." in txt
    assert "DRY_RUN=true" in txt


def test_safe_output_human_chat_success():
    txt = so.render_human_output(_out(interface="chat"))
    assert "[NOMOS-MC-CHAT-DRY-RUN]" in txt
    assert "Conselho simulado com segurança." in txt


def test_safe_output_gate_blocked_cli():
    txt = so.render_gate_blocked_output("cli")
    assert "[NOMOS-MC-GATE-BLOCKED]" in txt
    assert "Conteúdo bloqueado não será exibido." in txt


def test_safe_output_gate_blocked_chat():
    txt = so.render_gate_blocked_output("chat")
    assert "[NOMOS-MC-CHAT-GATE-BLOCKED]" in txt


def test_safe_output_denied_cli():
    txt = so.render_denied_output("cli")
    assert "[NOMOS-MC-CLI-DENIED]" in txt
    assert "Nada foi executado." in txt


def test_safe_output_denied_chat():
    txt = so.render_denied_output("chat")
    assert "[NOMOS-MC-CHAT-DENIED]" in txt


def test_safe_output_exception_cli():
    txt = so.render_exception_output("cli")
    assert "[NOMOS-MC-BLOCKED]" in txt
    assert "fail-closed" in txt


def test_safe_output_exception_chat():
    txt = so.render_exception_output("chat")
    assert "[NOMOS-MC-CHAT-BLOCKED]" in txt


def test_safe_output_gate_blocked_via_human_render():
    o = so.build_safe_output(_Result(allowed=False, blocked=True,
                                     failure_code=_EnumFC("ORCH_POLICY_GATE_DENIED")),
                             interface="cli", mode="critical", private_mode=False)
    txt = so.render_human_output(o)
    assert "[NOMOS-MC-GATE-BLOCKED]" in txt


# --------------------------------------------------------------------------
# Não vazar prompt/conteúdo/segredos
# --------------------------------------------------------------------------

def test_safe_output_does_not_echo_prompt_like_fields():
    # Um result com campos perigosos preenchidos não pode vazar nada deles.
    r = _Result()
    r.prompt = "SEGREDO-prompt-123"
    r.content = "SEGREDO-content-456"
    o = so.build_safe_output(r, interface="cli", mode="balanced", private_mode=False)
    saida = so.render_json_output(o) + "\n" + so.render_human_output(o)
    assert "SEGREDO" not in saida


def test_safe_output_does_not_emit_content_fields():
    payload = json.loads(so.render_json_output(_out()))
    for chave in ("content", "final_content", "candidate_content", "prompt"):
        assert chave not in payload


def test_safe_output_does_not_emit_engine_id():
    r = _Result()
    r.engine_id = "local:mistral-SECRET"
    o = so.build_safe_output(r, interface="chat", mode="fast", private_mode=False)
    saida = so.render_json_output(o) + so.render_human_output(o)
    assert "engine_id" not in saida
    assert "SECRET" not in saida


def test_safe_output_does_not_emit_secret_token_api_key():
    r = _Result()
    r.secret = "sk-SECRET"
    r.token = "tok-SECRET"
    r.api_key = "key-SECRET"
    o = so.build_safe_output(r, interface="cli", mode="balanced", private_mode=False)
    saida = so.render_json_output(o) + so.render_human_output(o)
    for chave in ("secret", "token", "api_key", "authorization", "bearer"):
        assert chave not in saida
    assert "SECRET" not in saida


def test_safe_output_json_renderer_outputs_json_object():
    payload = json.loads(so.render_json_output(_out()))
    assert isinstance(payload, dict)


def test_safe_output_json_renderer_does_not_include_raw_result():
    r = _Result()
    r.trace = {"leak": "SEGREDO"}
    r.audit_envelope = {"leak": "SEGREDO"}
    o = so.build_safe_output(r, interface="cli", mode="balanced", private_mode=False)
    saida = so.render_json_output(o)
    assert "SEGREDO" not in saida
    assert "trace" not in saida
    assert "audit_envelope" not in saida


def test_safe_output_failure_code_normalized_from_enum():
    o = so.build_safe_output(_Result(allowed=False, blocked=True,
                                     failure_code=_EnumFC("ORCH_NO_CANDIDATES")),
                             interface="cli", mode="fast", private_mode=False)
    assert o.failure_code == "ORCH_NO_CANDIDATES"


def test_safe_output_failure_code_normalized_from_plain_string():
    o = so.build_safe_output(_Result(allowed=False, blocked=True,
                                     failure_code="ORCH_NO_CANDIDATES"),
                             interface="chat", mode="fast", private_mode=False)
    assert o.failure_code == "ORCH_NO_CANDIDATES"
    assert isinstance(o.failure_code, str)


# --------------------------------------------------------------------------
# Pureza / segurança por AST
# --------------------------------------------------------------------------

def _imports():
    src = open(so.__file__, encoding="utf-8").read()
    nomes = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            nomes.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            nomes.add(node.module)
    return nomes


def _fonte():
    return open(so.__file__, encoding="utf-8").read()


def test_safe_output_module_does_not_import_network():
    proibidos = {"socket", "ssl", "http", "http.client", "urllib",
                 "urllib.request", "requests", "httpx", "aiohttp", "ftplib",
                 "smtplib"}
    assert not (_imports() & proibidos), _imports() & proibidos


def test_safe_output_module_does_not_import_subprocess_threading_asyncio():
    proibidos = {"subprocess", "threading", "multiprocessing", "asyncio",
                 "concurrent.futures", "signal"}
    assert not (_imports() & proibidos), _imports() & proibidos


def test_safe_output_module_does_not_import_cloud_clients():
    usados = _imports()
    prefixos = ("openai", "anthropic", "google", "google.generativeai", "gemini",
                "cohere", "boto3", "azure", "vertexai", "ollama", "llama_cpp",
                "transformers", "torch")
    ruins = [m for m in usados if any(m == p or m.startswith(p + ".") for p in prefixos)]
    assert not ruins, ruins


def test_safe_output_module_does_not_touch_filesystem_or_env():
    src = _fonte()
    assert "environ" not in src
    assert "getenv" not in src
    assert "open(" not in src
    assert "write_text" not in src
    assert "write_bytes" not in src


def test_safe_output_module_does_not_use_time_or_random():
    usados = _imports()
    assert "time" not in usados
    assert "random" not in usados
    assert "secrets" not in usados
    src = _fonte()
    assert ".now(" not in src
    assert "random." not in src
    assert "time." not in src


def test_safe_output_module_does_not_import_council_runtime_or_kernel():
    usados = _imports()
    prefixos = ("nomos.council.local_harness", "nomos.council.orchestrator",
                "nomos.council.cli_dry_run", "nomos.council.chat_dry_run",
                "nomos.kernel", "nomos.cognition", "nomos.runtime",
                "nomos.agents", "nomos.ext")
    ruins = [m for m in usados if any(m == p or m.startswith(p + ".") for p in prefixos)]
    assert not ruins, ruins


def test_safe_output_json_has_no_forbidden_substrings():
    # A saída JSON de um result "sujo" não pode conter nenhuma chave proibida.
    r = _Result()
    for nome in _FORBIDDEN_SUBSTRINGS:
        setattr(r, nome, "SEGREDO")
    o = so.build_safe_output(r, interface="chat", mode="balanced", private_mode=True)
    saida = so.render_json_output(o)
    assert "SEGREDO" not in saida
    for nome in _FORBIDDEN_SUBSTRINGS:
        assert nome not in saida
