"""MC8 — segurança/pureza do orquestrador dry-run.

Prova por AST que `orchestrator` não importa rede/subprocess/threading/asyncio/
SDK cloud/motor (inclusive o harness de execução real, que nem é importado),
não toca FS, não usa env/time/random, e não chama policy/vault/audit/approval
reais. Também prova que o adaptador dry-run usado pelo provider padrão nunca
teria `would_execute=true`.
"""
import ast

from nomos.council import orchestrator
from nomos.council.local_adapter import DryRunLocalEngineAdapter
from nomos.council.local_provider import LocalCandidateRequest, LocalEngineDescriptor


def _imports():
    src = open(orchestrator.__file__, encoding="utf-8").read()
    nomes = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            nomes.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            nomes.add(node.module)
    return nomes


def _fonte():
    return open(orchestrator.__file__, encoding="utf-8").read()


def test_orchestrator_module_does_not_import_network():
    proibidos = {"socket", "ssl", "http", "http.client", "urllib",
                 "urllib.request", "requests", "httpx", "aiohttp", "ftplib", "smtplib"}
    assert not (_imports() & proibidos), _imports() & proibidos


def test_orchestrator_module_does_not_import_subprocess_threading_asyncio():
    proibidos = {"subprocess", "threading", "multiprocessing", "asyncio",
                 "concurrent.futures", "signal"}
    assert not (_imports() & proibidos), _imports() & proibidos


def test_orchestrator_module_does_not_import_cloud_clients():
    usados = _imports()
    prefixos = ("openai", "anthropic", "google", "google.generativeai", "gemini",
                "cohere", "boto3", "azure", "vertexai")
    ruins = [m for m in usados if any(m == p or m.startswith(p + ".") for p in prefixos)]
    assert not ruins, ruins


def test_orchestrator_module_does_not_import_runtime_engines():
    usados = _imports()
    prefixos = ("ollama", "llama_cpp", "llama", "transformers", "torch",
                "nomos.cognition", "nomos.runtime", "nomos.motores")
    ruins = [m for m in usados if any(m == p or m.startswith(p + ".") for p in prefixos)]
    assert not ruins, ruins


def test_orchestrator_module_does_not_touch_filesystem_or_env():
    usados = _imports()
    io_env = {"pathlib", "os", "io", "sqlite3", "shutil", "tempfile"}
    assert not (usados & io_env), usados & io_env
    src = _fonte()
    assert "environ" not in src and "getenv" not in src


def test_orchestrator_module_does_not_use_time_or_random():
    usados = _imports()
    assert not (usados & {"time", "datetime", "random", "secrets"}), usados
    src = _fonte()
    assert ".now(" not in src


def test_orchestrator_does_not_call_policy_vault_audit_approval():
    usados = _imports()
    reais = {"nomos.kernel.policy", "nomos.kernel.vault", "nomos.kernel.audit",
             "nomos.kernel.audit_anchor", "nomos.kernel.localidade",
             "nomos.kernel.consent", "nomos.kernel.approvals"}
    assert not (usados & reais), usados & reais
    externos = {m for m in usados if m.startswith("nomos.")}
    permitidos = {"nomos.council.models", "nomos.council.local_provider",
                  "nomos.council.local_adapter", "nomos.council.simulator",
                  "nomos.council.policy_gate", "nomos.council.audit_envelope"}
    assert externos <= permitidos, externos


def test_orchestrator_does_not_call_real_harness_execute():
    # o orquestrador nem IMPORTA o harness de execução real (MC5) — não há
    # caminho algum, direto ou indireto, para execução real por este módulo.
    assert "local_harness" not in _imports()
    src = _fonte()
    assert "LocalExecutionHarness" not in src
    assert "REAL_LOCAL_ENGINE_EXECUTION_ENABLED" not in src
    assert ".execute(" not in src


def test_orchestrator_dry_run_adapter_would_execute_false():
    # a camada que o provider padrão usa (MC4) nunca teria would_execute=true
    adaptador = DryRunLocalEngineAdapter()
    descritor = LocalEngineDescriptor(engine_id="local:mock-a")
    pedido = LocalCandidateRequest(prompt="teste de adaptador", max_candidates=1)
    plano = adaptador.plan(descritor, pedido)
    resultado = adaptador.dry_run(descritor, pedido)
    assert plano.dry_run is True and plano.would_execute is False
    assert resultado.plan.would_execute is False


def test_orchestrator_only_stdlib_and_council_imports():
    usados = _imports()
    permitidos_topo = {"__future__", "json", "dataclasses", "enum", "nomos"}
    externos = {m.split(".")[0] for m in usados} - permitidos_topo
    assert not externos, f"imports inesperados: {externos}"


def test_orchestrator_module_does_not_reference_agents_skills_router():
    # escopo MC8 nunca compõe agentes, skills ou o roteador global
    usados = _imports()
    proibidos = {"nomos.agents", "nomos.skills", "nomos.router"}
    ruins = [m for m in usados if any(m == p or m.startswith(p + ".") for p in proibidos)]
    assert not ruins, ruins
    src = _fonte()
    assert "nomos conselho" not in src and "/conselho" not in src
