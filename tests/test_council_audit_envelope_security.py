"""MC7 — segurança/pureza do audit envelope dry-run.

Prova por AST que `audit_envelope` não importa rede/subprocess/threading/asyncio/
SDK cloud/motor, não toca FS, não usa env/time/random, e não chama
policy/vault/audit/approval reais.
"""
import ast

from nomos.council import audit_envelope


def _imports():
    src = open(audit_envelope.__file__, encoding="utf-8").read()
    nomes = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            nomes.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            nomes.add(node.module)
    return nomes


def test_audit_envelope_module_does_not_import_network():
    proibidos = {"socket", "ssl", "http", "http.client", "urllib",
                 "urllib.request", "requests", "httpx", "aiohttp", "ftplib", "smtplib"}
    assert not (_imports() & proibidos), _imports() & proibidos


def test_audit_envelope_module_does_not_import_subprocess_threading_asyncio():
    proibidos = {"subprocess", "threading", "multiprocessing", "asyncio",
                 "concurrent.futures", "signal"}
    assert not (_imports() & proibidos), _imports() & proibidos


def test_audit_envelope_module_does_not_import_cloud_clients():
    usados = _imports()
    prefixos = ("openai", "anthropic", "google", "google.generativeai", "gemini",
                "cohere", "boto3", "azure", "vertexai")
    ruins = [m for m in usados if any(m == p or m.startswith(p + ".") for p in prefixos)]
    assert not ruins, ruins


def test_audit_envelope_module_does_not_import_runtime_engines():
    usados = _imports()
    prefixos = ("ollama", "llama_cpp", "llama", "transformers", "torch",
                "nomos.cognition", "nomos.runtime", "nomos.motores")
    ruins = [m for m in usados if any(m == p or m.startswith(p + ".") for p in prefixos)]
    assert not ruins, ruins


def test_audit_envelope_module_does_not_touch_filesystem_or_env():
    usados = _imports()
    io_env = {"pathlib", "os", "io", "sqlite3", "shutil", "tempfile"}
    assert not (usados & io_env), usados & io_env
    src = open(audit_envelope.__file__, encoding="utf-8").read()
    assert "environ" not in src and "getenv" not in src


def test_audit_envelope_module_does_not_use_time_or_random():
    usados = _imports()
    assert not (usados & {"time", "datetime", "random", "secrets"}), usados
    src = open(audit_envelope.__file__, encoding="utf-8").read()
    assert ".now(" not in src


def test_audit_envelope_does_not_call_policy_vault_audit_approval():
    usados = _imports()
    reais = {"nomos.kernel.policy", "nomos.kernel.vault", "nomos.kernel.audit",
             "nomos.kernel.audit_anchor", "nomos.kernel.localidade",
             "nomos.kernel.consent", "nomos.kernel.approvals"}
    assert not (usados & reais), usados & reais
    externos = {m for m in usados if m.startswith("nomos.")}
    assert externos <= {"nomos.council.models"}, externos


def test_audit_envelope_only_stdlib_and_models():
    usados = _imports()
    permitidos_topo = {"__future__", "json", "dataclasses", "enum", "nomos"}
    externos = {m.split(".")[0] for m in usados} - permitidos_topo
    assert not externos, f"imports inesperados: {externos}"
