"""MC3 — segurança/pureza do provedor de candidatos locais.

Prova por AST que `local_provider` não importa rede/subprocess/threading/asyncio/
SDK cloud/motor real, não toca FS, não usa env, tempo real ou random, e não
chama policy/vault/audit reais.
"""
import ast

from nomos.council import local_provider


def _imports():
    src = open(local_provider.__file__, encoding="utf-8").read()
    nomes = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            nomes.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            nomes.add(node.module)
    return nomes


def test_local_provider_module_does_not_import_network():
    proibidos = {"socket", "ssl", "http", "http.client", "urllib",
                 "urllib.request", "requests", "httpx", "aiohttp", "ftplib", "smtplib"}
    assert not (_imports() & proibidos), _imports() & proibidos


def test_local_provider_module_does_not_import_subprocess_threading_asyncio():
    proibidos = {"subprocess", "threading", "multiprocessing", "asyncio",
                 "concurrent.futures", "signal"}
    assert not (_imports() & proibidos), _imports() & proibidos


def test_local_provider_module_does_not_import_cloud_clients():
    usados = _imports()
    prefixos = ("openai", "anthropic", "google", "google.generativeai", "gemini",
                "cohere", "boto3", "azure", "vertexai")
    ruins = [m for m in usados
             if any(m == p or m.startswith(p + ".") for p in prefixos)]
    assert not ruins, ruins


def test_local_provider_module_does_not_import_runtime_engines():
    usados = _imports()
    prefixos = ("ollama", "llama_cpp", "llama", "transformers", "torch",
                "nomos.cognition", "nomos.runtime", "nomos.motores")
    ruins = [m for m in usados
             if any(m == p or m.startswith(p + ".") for p in prefixos)]
    assert not ruins, ruins


def test_local_provider_module_does_not_touch_filesystem_or_env():
    usados = _imports()
    io_env = {"pathlib", "os", "io", "sqlite3", "shutil", "tempfile"}
    assert not (usados & io_env), usados & io_env
    src = open(local_provider.__file__, encoding="utf-8").read()
    assert "environ" not in src and "getenv" not in src


def test_local_provider_module_does_not_call_policy_vault_audit():
    usados = _imports()
    reais = {"nomos.kernel.policy", "nomos.kernel.vault", "nomos.kernel.audit",
             "nomos.kernel.audit_anchor", "nomos.kernel.localidade",
             "nomos.kernel.consent"}
    assert not (usados & reais), usados & reais
    externos = {m for m in usados if m.startswith("nomos.")}
    assert externos <= {"nomos.council.models", "nomos.council.simulator"}, externos


def test_local_provider_module_no_time_or_random():
    """Determinismo: sem tempo real nem aleatoriedade."""
    usados = _imports()
    assert not (usados & {"time", "datetime", "random", "secrets", "uuid"}), usados


def test_local_provider_only_stdlib_and_council():
    usados = _imports()
    permitidos_topo = {"__future__", "dataclasses", "typing", "nomos"}
    externos = {m.split(".")[0] for m in usados} - permitidos_topo
    assert not externos, f"imports inesperados: {externos}"
