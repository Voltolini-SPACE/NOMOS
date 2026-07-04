"""MC3 — segurança/pureza da camada de motor local.

Prova por AST que `local_engine` não importa rede/subprocess/threading/asyncio/
SDK cloud/motor, não toca FS, não usa env, e não chama policy/vault/audit reais.
"""
import ast

from nomos.council import local_engine


def _imports():
    src = open(local_engine.__file__, encoding="utf-8").read()
    nomes = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            nomes.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            nomes.add(node.module)
    return nomes


def test_local_engine_module_does_not_import_network():
    proibidos = {"socket", "ssl", "http", "http.client", "urllib",
                 "urllib.request", "requests", "httpx", "aiohttp", "ftplib", "smtplib"}
    assert not (_imports() & proibidos), _imports() & proibidos


def test_local_engine_module_does_not_import_subprocess_threading_asyncio():
    proibidos = {"subprocess", "threading", "multiprocessing", "asyncio",
                 "concurrent.futures", "signal"}
    assert not (_imports() & proibidos), _imports() & proibidos


def test_local_engine_module_does_not_import_cloud_clients():
    usados = _imports()
    prefixos = ("openai", "anthropic", "ollama", "cohere", "google",
                "boto3", "azure", "vertexai", "llama_cpp", "transformers", "torch")
    ruins = [m for m in usados
             if any(m == p or m.startswith(p + ".") for p in prefixos)]
    assert not ruins, ruins


def test_local_engine_module_does_not_touch_filesystem():
    usados = _imports()
    io_proibido = {"pathlib", "os", "io", "sqlite3", "shutil", "tempfile"}
    assert not (usados & io_proibido), usados & io_proibido


def test_local_engine_module_does_not_call_policy_vault_audit():
    usados = _imports()
    reais = {"nomos.kernel.policy", "nomos.kernel.vault", "nomos.kernel.audit",
             "nomos.kernel.audit_anchor", "nomos.kernel.localidade",
             "nomos.kernel.consent", "nomos.cognition.router"}
    assert not (usados & reais), usados & reais
    externos = {m for m in usados if m.startswith("nomos.")}
    assert externos <= {"nomos.council.models", "nomos.council.simulator"}, externos


def test_local_engine_module_no_environ_reference():
    """Não lê variáveis de ambiente (nenhuma menção a os.environ/getenv)."""
    src = open(local_engine.__file__, encoding="utf-8").read()
    assert "environ" not in src and "getenv" not in src


def test_local_engine_only_stdlib_and_council():
    usados = _imports()
    permitidos_topo = {"__future__", "dataclasses", "typing", "nomos"}
    externos = {m.split(".")[0] for m in usados} - permitidos_topo
    assert not externos, f"imports inesperados: {externos}"


def test_local_engine_deterministic_same_input_same_output():
    from nomos.council.local_engine import (DeterministicLocalCandidateProvider,
                                            LocalCandidateRequest,
                                            run_offline_council_with_local_candidates)
    from nomos.council.simulator import SimulatedJudgeFixture
    req = LocalCandidateRequest(prompt="determinismo", max_candidates=2)
    judges = [SimulatedJudgeFixture("fixture:j1", "A", overall=5),
              SimulatedJudgeFixture("fixture:j2", "B", overall=4)]
    a = run_offline_council_with_local_candidates(
        req, DeterministicLocalCandidateProvider(), judges).to_json()
    b = run_offline_council_with_local_candidates(
        req, DeterministicLocalCandidateProvider(), judges).to_json()
    assert a == b
