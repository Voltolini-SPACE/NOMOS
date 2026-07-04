"""MC5 — harness de execução local FAIL-CLOSED."""
import ast
import json
import types

import pytest

from nomos.council import local_harness
from nomos.council.local_harness import (
    REAL_LOCAL_ENGINE_EXECUTION_ENABLED,
    ExecutionFailureCode,
    HarnessError,
    LocalExecutionAttemptRecord,
    LocalExecutionHarness,
    LocalExecutionRequest,
    LocalExecutionResult,
)

H = LocalExecutionHarness()
SEG = "PROMPT-SECRETO-HARNESS-77"


# ---------------- flag literal ----------------

def test_real_execution_flag_is_literal_false():
    assert REAL_LOCAL_ENGINE_EXECUTION_ENABLED is False
    # o VALOR no código-fonte é o literal False (não env/config/call/nome)
    src = open(local_harness.__file__, encoding="utf-8").read()
    achou = False
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Assign):
            for alvo in node.targets:
                if (isinstance(alvo, ast.Name)
                        and alvo.id == "REAL_LOCAL_ENGINE_EXECUTION_ENABLED"):
                    assert isinstance(node.value, ast.Constant)
                    assert node.value.value is False
                    achou = True
    assert achou, "constante da trava não encontrada como literal"


# ---------------- request ----------------

def test_execution_request_rejects_non_local_engine():
    with pytest.raises(HarnessError, match="local:"):
        LocalExecutionRequest(engine_id="remote:model")


def test_execution_request_repr_does_not_leak_prompt():
    req = LocalExecutionRequest.from_prompt(SEG, engine_id="local:m")
    assert SEG not in repr(req)
    assert SEG not in json.dumps(req.to_dict(), ensure_ascii=False)
    assert req.prompt_chars == len(SEG)   # só o tamanho é guardado


# ---------------- harness fail-closed ----------------

def test_execution_harness_blocks_by_default():
    r = H.execute(LocalExecutionRequest(engine_id="local:mock-a"))
    assert r.allowed is False
    assert r.failure_code is ExecutionFailureCode.REAL_EXECUTION_DISABLED


def test_execution_harness_never_executes():
    r = H.execute(LocalExecutionRequest(engine_id="local:mock-a"))
    assert r.executed is False and r.attempt.executed is False


def test_execution_harness_returns_no_candidate():
    r = H.execute(LocalExecutionRequest(engine_id="local:mock-a"))
    assert r.candidate is None
    assert r.to_dict()["candidate"] is None


def test_execution_harness_non_local_engine_fails_closed():
    fake = types.SimpleNamespace(engine_id="remote:model",
                                 adapter_id="dryrun:x", private_mode=False)
    r = H.execute(fake)
    assert r.failure_code is ExecutionFailureCode.REAL_EXECUTION_ENGINE_NOT_LOCAL
    assert r.executed is False and r.candidate is None


def test_execution_harness_private_mode_disables_persist():
    r = H.execute(LocalExecutionRequest(engine_id="local:m", private_mode=True))
    assert r.attempt.persist_allowed is False
    assert r.executed is False


def test_execution_harness_env_cannot_enable(monkeypatch):
    monkeypatch.setenv("NOMOS_REAL_LOCAL_ENGINE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("REAL_LOCAL_ENGINE_EXECUTION_ENABLED", "true")
    r = H.execute(LocalExecutionRequest(engine_id="local:m"))
    assert r.executed is False
    assert r.failure_code is ExecutionFailureCode.REAL_EXECUTION_DISABLED


# ---------------- serialização ----------------

def test_execution_result_roundtrip_json():
    r = H.execute(LocalExecutionRequest(engine_id="local:m"))
    d = r.to_dict()
    assert json.loads(json.dumps(d, sort_keys=True)) == d
    assert d["schema"] == "nomos.council.local_execution_result.v1"
    assert d["executed"] is False and d["allowed"] is False


def test_execution_attempt_roundtrip_json():
    a = LocalExecutionAttemptRecord(engine_id="local:m", adapter_id="dryrun:x",
                                    block_reason="REAL_EXECUTION_DISABLED")
    d = a.to_dict()
    assert json.loads(json.dumps(d, sort_keys=True)) == d
    assert d["executed"] is False and d["blocked"] is True


def test_execution_result_repr_redacts_sensitive_data():
    req = LocalExecutionRequest.from_prompt(SEG, engine_id="local:m",
                                            contains_sensitive_data=True)
    r = H.execute(req)
    assert SEG not in repr(r)
    assert SEG not in json.dumps(r.to_dict(), ensure_ascii=False)


def test_execution_attempt_repr_redacts_sensitive_data():
    r = H.execute(LocalExecutionRequest.from_prompt(SEG, engine_id="local:m"))
    assert SEG not in repr(r.attempt)
    assert SEG not in json.dumps(r.attempt.to_dict(), ensure_ascii=False)


# ---------------- determinismo / estado ----------------

def test_execution_harness_deterministic_same_input():
    a = H.execute(LocalExecutionRequest(engine_id="local:m")).to_dict()
    b = H.execute(LocalExecutionRequest(engine_id="local:m")).to_dict()
    assert a == b


def test_execution_harness_does_not_change_global_flag():
    antes = local_harness.REAL_LOCAL_ENGINE_EXECUTION_ENABLED
    for _ in range(3):
        H.execute(LocalExecutionRequest(engine_id="local:m"))
    assert local_harness.REAL_LOCAL_ENGINE_EXECUTION_ENABLED is antes is False


def test_dry_run_adapter_still_works_after_harness():
    # o MC4 continua intacto após a introdução do harness
    from nomos.council.local_adapter import DryRunLocalEngineAdapter
    from nomos.council.local_provider import (LocalCandidateRequest,
                                             LocalEngineDescriptor)
    H.execute(LocalExecutionRequest(engine_id="local:m"))   # não afeta o dry-run
    d = DryRunLocalEngineAdapter().dry_run(
        LocalEngineDescriptor("local:m"), LocalCandidateRequest(prompt="x"))
    assert d.allowed is True and d.plan.dry_run is True and d.plan.would_execute is False


def test_result_is_execution_result_type():
    assert isinstance(H.execute(LocalExecutionRequest(engine_id="local:m")),
                      LocalExecutionResult)
