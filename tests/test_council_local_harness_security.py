"""MC5 — segurança/pureza do harness de execução local.

Prova por AST que `local_harness` não importa rede/subprocess/threading/asyncio/
SDK cloud/motor real, não toca FS, não usa env/time/random, não chama
policy/vault/audit, e NÃO expõe API para ativar execução real.
"""
import ast

from nomos.council import local_harness


def _tree():
    return ast.parse(open(local_harness.__file__, encoding="utf-8").read())


def _imports():
    nomes = set()
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Import):
            nomes.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            nomes.add(node.module)
    return nomes


def test_local_harness_module_does_not_import_network():
    proibidos = {"socket", "ssl", "http", "http.client", "urllib",
                 "urllib.request", "requests", "httpx", "aiohttp", "ftplib", "smtplib"}
    assert not (_imports() & proibidos), _imports() & proibidos


def test_local_harness_module_does_not_import_subprocess_threading_asyncio():
    proibidos = {"subprocess", "threading", "multiprocessing", "asyncio",
                 "concurrent.futures", "signal"}
    assert not (_imports() & proibidos), _imports() & proibidos


def test_local_harness_module_does_not_import_cloud_clients():
    usados = _imports()
    prefixos = ("openai", "anthropic", "google", "google.generativeai", "gemini",
                "cohere", "boto3", "azure", "vertexai")
    ruins = [m for m in usados if any(m == p or m.startswith(p + ".") for p in prefixos)]
    assert not ruins, ruins


def test_local_harness_module_does_not_import_runtime_engines():
    usados = _imports()
    prefixos = ("ollama", "llama_cpp", "llama", "transformers", "torch",
                "nomos.cognition", "nomos.runtime", "nomos.motores")
    ruins = [m for m in usados if any(m == p or m.startswith(p + ".") for p in prefixos)]
    assert not ruins, ruins


def test_local_harness_module_does_not_touch_filesystem_or_env():
    usados = _imports()
    io_env = {"pathlib", "os", "io", "sqlite3", "shutil", "tempfile"}
    assert not (usados & io_env), usados & io_env
    src = open(local_harness.__file__, encoding="utf-8").read()
    assert "environ" not in src and "getenv" not in src


def test_local_harness_module_does_not_use_time_or_random():
    usados = _imports()
    assert not (usados & {"time", "datetime", "random", "secrets"}), usados
    src = open(local_harness.__file__, encoding="utf-8").read()
    assert ".now(" not in src


def test_local_harness_does_not_call_policy_vault_audit():
    usados = _imports()
    reais = {"nomos.kernel.policy", "nomos.kernel.vault", "nomos.kernel.audit",
             "nomos.kernel.audit_anchor", "nomos.kernel.localidade",
             "nomos.kernel.consent"}
    assert not (usados & reais), usados & reais
    externos = {m for m in usados if m.startswith("nomos.")}
    assert externos <= {"nomos.council.models"}, externos


def test_local_harness_has_no_enable_or_activate_api():
    # nem no namespace do módulo, nem como def no fonte
    proibidos = {"enable", "activate", "unlock", "set_enabled",
                 "enable_real_execution", "activate_real_execution",
                 "set_real_execution_enabled"}
    assert not (set(dir(local_harness)) & proibidos)
    # nenhuma função que LIGUE a trava: nomes que começam por enable/activate/
    # unlock ou o setter set_enabled. (getter read-only 'real_execution_enabled' ok.)
    for node in ast.walk(_tree()):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            nome = node.name.lower()
            assert not nome.startswith(("enable", "activate", "unlock")), node.name
            assert nome != "set_enabled" and "set_enabled" not in nome, node.name
    # a constante nunca é reatribuída no módulo (fora da definição inicial)
    reatrib = 0
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Assign):
            for alvo in node.targets:
                if isinstance(alvo, ast.Name) and \
                        alvo.id == "REAL_LOCAL_ENGINE_EXECUTION_ENABLED":
                    reatrib += 1
    assert reatrib == 1, "a trava só pode ser definida uma vez (literal)"


def test_local_harness_only_stdlib_and_models():
    usados = _imports()
    permitidos_topo = {"__future__", "json", "dataclasses", "enum", "nomos"}
    externos = {m.split(".")[0] for m in usados} - permitidos_topo
    assert not externos, f"imports inesperados: {externos}"
