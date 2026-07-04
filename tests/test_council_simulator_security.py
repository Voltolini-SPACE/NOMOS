"""MC2 — segurança/pureza do simulador offline.

Prova por AST que o simulador não importa rede/subprocess/threading/asyncio/
motor, e por contrato que não toca disco nem chama policy/vault/audit reais, e
que o prompt privado não vaza no repr.
"""
import ast

from nomos.council import simulator
from nomos.council.simulator import (
    OfflineCouncilInput,
    OfflineCouncilSimulator,
    SimulatedEngineFixture,
    SimulatedJudgeFixture,
)

SEGREDO = "PROMPT-PRIVADO-CONFIDENCIAL-99"
SIM = OfflineCouncilSimulator()


def _imports():
    src = open(simulator.__file__, encoding="utf-8").read()
    nomes = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            nomes.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            nomes.add(node.module)
    return nomes


def test_simulator_does_not_import_network_modules():
    proibidos = {"socket", "ssl", "http", "http.client", "urllib",
                 "urllib.request", "requests", "httpx", "aiohttp", "ftplib", "smtplib"}
    assert not (_imports() & proibidos), _imports() & proibidos


def test_simulator_does_not_import_subprocess_threading_asyncio():
    proibidos = {"subprocess", "threading", "multiprocessing", "asyncio",
                 "concurrent.futures", "signal"}
    assert not (_imports() & proibidos), _imports() & proibidos


def test_simulator_does_not_import_engine_modules():
    usados = _imports()
    prefixos = ("nomos.cognition", "nomos.runtime", "nomos.ext",
                "llama", "torch", "transformers", "ollama")
    ruins = [m for m in usados
             if any(m == p or m.startswith(p + ".") for p in prefixos)]
    assert not ruins, ruins


def test_simulator_does_not_touch_filesystem():
    """Nenhum import de I/O de arquivo/persistência; só stdlib puro + models."""
    usados = _imports()
    io_proibido = {"pathlib", "os", "io", "sqlite3", "shutil", "tempfile",
                   "open"}  # 'open' não é import, mas garantimos ausência de os/pathlib
    assert not (usados & io_proibido), usados & io_proibido


def test_simulator_does_not_call_policy_vault_audit():
    usados = _imports()
    reais = {"nomos.kernel.policy", "nomos.kernel.vault", "nomos.kernel.audit",
             "nomos.kernel.audit_anchor", "nomos.kernel.localidade",
             "nomos.kernel.consent"}
    assert not (usados & reais), usados & reais
    # só importa os modelos puros do council
    externos = {m for m in usados if m.startswith("nomos.")}
    assert externos <= {"nomos.council.models"}, externos


def test_simulator_private_prompt_not_in_repr():
    inp = OfflineCouncilInput(prompt=SEGREDO, private_mode=True,
                              candidate_fixtures=[SimulatedEngineFixture(
                                  "fixture:a", "cand_a", "resp")],
                              judge_fixtures=[SimulatedJudgeFixture(
                                  "fixture:j", "A", overall=4)])
    assert SEGREDO not in repr(inp)
    # o prompt também nunca aparece no resultado serializado (não é propagado)
    r = SIM.run(inp)
    assert SEGREDO not in r.to_json()


def test_simulator_fixture_repr_redacts_content():
    fx = SimulatedEngineFixture("fixture:a", "cand_a", content=SEGREDO)
    assert SEGREDO not in repr(fx)


def test_simulator_result_deterministic_no_time_no_random():
    """Sem tempo/random: dois runs idênticos byte a byte."""
    inp = OfflineCouncilInput(prompt="p", candidate_fixtures=[
        SimulatedEngineFixture("fixture:a", "cand_a", "A"),
        SimulatedEngineFixture("fixture:b", "cand_b", "B")],
        judge_fixtures=[SimulatedJudgeFixture("fixture:j1", "A", overall=5),
                        SimulatedJudgeFixture("fixture:j2", "B", overall=4)])
    assert SIM.run(inp).to_json() == SIM.run(inp).to_json()


def test_simulator_only_stdlib_and_models():
    usados = _imports()
    permitidos_topo = {"__future__", "json", "dataclasses", "nomos"}
    externos = {m.split(".")[0] for m in usados} - permitidos_topo
    assert not externos, f"imports inesperados: {externos}"
