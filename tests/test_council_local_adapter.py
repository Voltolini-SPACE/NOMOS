"""MC4 — contratos do adaptador de motor local em SPEC/DRY-RUN."""
import json
import types

import pytest

from nomos.council.local_adapter import (
    AdapterError,
    AdapterFailureCode,
    DryRunAdapterCandidateProvider,
    DryRunLocalEngineAdapter,
    LocalEngineAdapterPolicy,
    LocalEngineDryRunResult,
    LocalEngineExecutionPlan,
    LocalEngineIsolationProfile,
)
from nomos.council.local_provider import (
    LocalCandidateRequest,
    LocalEngineDescriptor,
    run_offline_council_with_local_provider,
)
from nomos.council.models import CouncilFailureCode
from nomos.council.simulator import SimulatedJudgeFixture, SimulatedPolicyGateResult

A = DryRunLocalEngineAdapter()
LOCAL = LocalEngineDescriptor("local:mock-a")
REQ = LocalCandidateRequest(prompt="oi")


def _judges(pairs):
    return [SimulatedJudgeFixture(f"fixture:j{i}", a, overall=o)
            for i, (a, o) in enumerate(pairs)]


# ---------------- isolation profile ----------------

def test_isolation_profile_defaults_deny_all():
    p = LocalEngineIsolationProfile()
    d = p.to_dict()
    for k in ("network_allowed", "subprocess_allowed", "filesystem_allowed",
              "env_allowed", "cloud_allowed", "loopback_allowed"):
        assert d[k] is False


def test_isolation_profile_rejects_network_allowed():
    with pytest.raises(AdapterError, match="isolamento"):
        LocalEngineIsolationProfile(network_allowed=True)
    with pytest.raises(AdapterError):
        LocalEngineIsolationProfile(loopback_allowed=True)


# ---------------- adapter policy ----------------

def test_adapter_policy_defaults_dry_run_local_only():
    p = LocalEngineAdapterPolicy()
    assert p.dry_run_only is True and p.local_only is True
    assert p.max_prompt_chars > 0 and p.max_output_chars > 0


def test_adapter_policy_rejects_cloud_allowed():
    with pytest.raises(AdapterError, match="allow_cloud"):
        LocalEngineAdapterPolicy(allow_cloud=True)


def test_adapter_policy_rejects_network_allowed():
    with pytest.raises(AdapterError, match="allow_network"):
        LocalEngineAdapterPolicy(allow_network=True)
    with pytest.raises(AdapterError):
        LocalEngineAdapterPolicy(dry_run_only=False)


# ---------------- execution plan ----------------

def test_execution_plan_never_would_execute():
    plano = A.plan(LOCAL, REQ)
    assert plano.would_execute is False and plano.dry_run is True
    # mesmo forçando would_execute=True na construção, é normalizado p/ False
    forcado = LocalEngineExecutionPlan(engine_id="local:x", prompt_chars=1,
                                       expected_output_chars=10, isolation={},
                                       policy={}, would_execute=True)
    assert forcado.would_execute is False


def test_execution_plan_repr_redacts_prompt():
    SEG = "PROMPT-PLANO-SEG"
    plano = A.plan(LOCAL, LocalCandidateRequest(prompt=SEG))
    assert SEG not in repr(plano)
    assert SEG not in json.dumps(plano.to_dict())
    assert plano.prompt_chars == len(SEG)


# ---------------- dry-run adapter ----------------

def test_dry_run_adapter_happy_path():
    r = A.dry_run(LOCAL, REQ)
    assert r.allowed is True and r.failure_code is None
    assert r.candidate is not None
    assert r.plan.would_execute is False and r.plan.dry_run is True


def test_dry_run_adapter_rejects_non_local_engine():
    # objeto duck-typed com engine_id não-local para exercitar a guarda do adapter
    fake = types.SimpleNamespace(engine_id="remote:model", cloud=False,
                                 network_required=False, local_only=True)
    r = A.dry_run(fake, REQ)
    assert r.allowed is False
    assert r.failure_code is AdapterFailureCode.ADAPTER_ENGINE_NOT_LOCAL
    assert r.candidate is None


def test_dry_run_adapter_rejects_cloud_engine():
    r = A.dry_run(LocalEngineDescriptor("local:x", cloud=True), REQ)
    assert r.allowed is False
    assert r.failure_code is AdapterFailureCode.ADAPTER_CLOUD_DENIED
    assert r.candidate is None


def test_dry_run_adapter_rejects_network_engine():
    r = A.dry_run(LocalEngineDescriptor("local:x", network_required=True), REQ)
    assert r.failure_code is AdapterFailureCode.ADAPTER_NETWORK_DENIED
    assert r.candidate is None


def test_dry_run_adapter_rejects_prompt_too_large():
    small = DryRunLocalEngineAdapter(policy=LocalEngineAdapterPolicy(max_prompt_chars=5))
    r = small.dry_run(LOCAL, LocalCandidateRequest(prompt="x" * 10))
    assert r.failure_code is AdapterFailureCode.ADAPTER_PROMPT_TOO_LARGE
    assert r.candidate is None


def test_dry_run_adapter_deterministic_same_input():
    assert A.dry_run(LOCAL, REQ).to_dict() == A.dry_run(LOCAL, REQ).to_dict()


# ---------------- dry-run result ----------------

def test_dry_run_result_roundtrip_json():
    r = A.dry_run(LOCAL, REQ)
    d = r.to_dict()
    s = json.dumps(d, sort_keys=True, ensure_ascii=False)
    assert json.loads(s) == d
    assert d["schema"] == "nomos.council.local_dry_run_result.v1"
    assert d["plan"]["would_execute"] is False


def test_dry_run_result_does_not_include_prompt():
    SEG = "PROMPT-RESULT-SEG"
    r = A.dry_run(LOCAL, LocalCandidateRequest(prompt=SEG))
    assert SEG not in json.dumps(r.to_dict(), ensure_ascii=False)
    assert SEG not in repr(r)
    assert isinstance(r, LocalEngineDryRunResult)


def test_dry_run_candidate_id_prefix():
    r = A.dry_run(LOCAL, REQ)
    assert r.candidate.candidate_id.startswith("dry_cand_")


# ---------------- provider via adapter ----------------

def test_dry_run_provider_generates_candidates():
    res = DryRunAdapterCandidateProvider().generate(
        LocalCandidateRequest(prompt="oi", max_candidates=2))
    assert res.failure_code is None and len(res.candidates) == 2
    for c in res.candidates:
        assert c.engine_id.startswith("local:")
        assert c.candidate_id.startswith("dry_cand_")


def test_dry_run_provider_fails_closed_when_adapter_blocks():
    prov = DryRunAdapterCandidateProvider(
        [LocalEngineDescriptor("local:x", cloud=True)])
    res = prov.generate(LocalCandidateRequest(prompt="x"))
    assert res.candidates == []
    assert res.failure_code is CouncilFailureCode.CLOUD_BLOCKED_BY_LOCAL_LOCK


def test_dry_run_provider_preserves_max_candidates():
    engines = [LocalEngineDescriptor(f"local:m{i}") for i in range(5)]
    res = DryRunAdapterCandidateProvider(engines).generate(
        LocalCandidateRequest(prompt="x", max_candidates=2))
    assert len(res.candidates) == 2


def test_dry_run_provider_integrates_with_offline_simulator():
    r = run_offline_council_with_local_provider(
        LocalCandidateRequest(prompt="oi", max_candidates=2),
        DryRunAdapterCandidateProvider(),
        judge_fixtures=_judges([("A", 5), ("B", 4)]),
        gate=SimulatedPolicyGateResult())
    assert r.failure_code is None
    assert r.arbiter_decision.blocked is False
    assert all(c.engine_id == "ANON" for c in r.anonymized_candidates)
