"""MC3 — contratos da integração de motores locais do Motor Council."""
import pytest

from nomos.council.local_engine import (
    DeterministicLocalCandidateProvider,
    LocalCandidateRequest,
    LocalCandidateResult,
    LocalEngineDescriptor,
    LocalEngineError,
    run_offline_council_with_local_candidates,
)
from nomos.council.models import CouncilFailureCode
from nomos.council.simulator import SimulatedJudgeFixture, SimulatedPolicyGateResult


def _judges(pairs):
    return [SimulatedJudgeFixture(f"fixture:j{i}", a, overall=o)
            for i, (a, o) in enumerate(pairs)]


# ---------------- descriptor ----------------

def test_local_engine_descriptor_requires_local_prefix():
    with pytest.raises(LocalEngineError, match="local:"):
        LocalEngineDescriptor(engine_id="remote:x")
    with pytest.raises(LocalEngineError, match="local:"):
        LocalEngineDescriptor(engine_id="openai:gpt")


def test_local_engine_descriptor_rejects_cloud():
    d = LocalEngineDescriptor(engine_id="local:x", cloud=True)
    assert d.is_eligible is False
    assert "cloud" in d.eligibility().reason


def test_local_engine_descriptor_rejects_network_required():
    d = LocalEngineDescriptor(engine_id="local:x", network_required=True)
    assert d.is_eligible is False
    assert "rede" in d.eligibility().reason


def test_local_engine_descriptor_local_is_eligible():
    d = LocalEngineDescriptor(engine_id="local:mock")
    assert d.is_eligible is True
    assert d.eligibility().eligible is True


# ---------------- request ----------------

def test_local_candidate_request_requires_prompt():
    with pytest.raises(LocalEngineError, match="prompt"):
        LocalCandidateRequest(prompt="")


def test_local_candidate_request_rejects_zero_candidates():
    with pytest.raises(LocalEngineError, match="max_candidates"):
        LocalCandidateRequest(prompt="x", max_candidates=0)


def test_local_request_sensitive_and_paranoid_never_allow_cloud():
    req = LocalCandidateRequest(prompt="x", contains_sensitive_data=True,
                                mode="paranoid")
    assert req.cloud_allowed is False
    assert req.local_only is True


def test_local_request_private_mode_no_persist():
    assert LocalCandidateRequest(prompt="x", private_mode=True).persist_allowed is False
    assert LocalCandidateRequest(prompt="x").persist_allowed is True


# ---------------- provider ----------------

def test_local_provider_lists_only_local_engines():
    prov = DeterministicLocalCandidateProvider()
    for e in prov.list_engines():
        assert e.engine_id.startswith("local:")


def test_local_provider_generates_answer_candidates():
    res = DeterministicLocalCandidateProvider().generate(
        LocalCandidateRequest(prompt="oi", max_candidates=2))
    assert res.failure_code is None
    assert len(res.candidates) == 2
    for c in res.candidates:
        assert c.engine_id.startswith("local:") and c.content


def test_local_provider_limits_max_candidates():
    engines = [LocalEngineDescriptor(f"local:m{i}") for i in range(5)]
    res = DeterministicLocalCandidateProvider(engines).generate(
        LocalCandidateRequest(prompt="x", max_candidates=2))
    assert len(res.candidates) == 2


def test_local_provider_fails_closed_without_eligible_engine():
    res = DeterministicLocalCandidateProvider([]).generate(
        LocalCandidateRequest(prompt="x"))
    assert res.candidates == []
    assert res.failure_code is CouncilFailureCode.NO_ELIGIBLE_LOCAL_ENGINE


def test_local_provider_fails_closed_for_cloud_engine():
    res = DeterministicLocalCandidateProvider(
        [LocalEngineDescriptor("local:x", cloud=True)]).generate(
        LocalCandidateRequest(prompt="x"))
    assert res.candidates == []
    assert res.failure_code is CouncilFailureCode.NO_ELIGIBLE_LOCAL_ENGINE
    assert any("cloud" in w for w in res.warnings)


def test_local_provider_fails_closed_for_network_engine():
    res = DeterministicLocalCandidateProvider(
        [LocalEngineDescriptor("local:x", network_required=True)]).generate(
        LocalCandidateRequest(prompt="x"))
    assert res.candidates == []
    assert res.failure_code is CouncilFailureCode.NO_ELIGIBLE_LOCAL_ENGINE


def test_local_provider_sensitive_data_never_allows_cloud():
    req = LocalCandidateRequest(prompt="x", contains_sensitive_data=True)
    res = DeterministicLocalCandidateProvider().generate(req)
    assert req.cloud_allowed is False
    for c in res.candidates:
        assert c.engine_id.startswith("local:")


def test_local_provider_paranoid_mode_local_only():
    req = LocalCandidateRequest(prompt="x", mode="paranoid")
    assert req.local_only is True
    res = DeterministicLocalCandidateProvider().generate(req)
    for c in res.candidates:
        assert c.engine_id.startswith("local:")


def test_local_provider_private_mode_does_not_persist_prompt():
    # o provider não guarda o prompt: nem no result, nem nos candidatos
    SEG = "PROMPT-PRIVADO-XYZ"
    res = DeterministicLocalCandidateProvider().generate(
        LocalCandidateRequest(prompt=SEG, private_mode=True))
    import json
    dump = json.dumps([c.to_dict() for c in res.candidates], ensure_ascii=False)
    assert SEG not in dump


def test_local_provider_result_repr_redacts_prompt():
    SEG = "PROMPT-SECRETO-123"
    res = DeterministicLocalCandidateProvider().generate(
        LocalCandidateRequest(prompt=SEG))
    assert SEG not in repr(res)
    assert isinstance(res, LocalCandidateResult)


# ---------------- integração com o simulador ----------------

def test_simulator_run_with_local_provider_happy_path():
    r = run_offline_council_with_local_candidates(
        LocalCandidateRequest(prompt="oi", max_candidates=2),
        DeterministicLocalCandidateProvider(),
        judge_fixtures=_judges([("A", 5), ("B", 4)]))
    assert r.failure_code is None
    assert r.arbiter_decision.blocked is False
    assert [c.engine_id for c in r.candidates] == ["local:mock-a", "local:mock-b"]
    assert all(c.engine_id == "ANON" for c in r.anonymized_candidates)


def test_simulator_run_with_local_provider_no_engine_fails_closed():
    r = run_offline_council_with_local_candidates(
        LocalCandidateRequest(prompt="x"),
        DeterministicLocalCandidateProvider([]), judge_fixtures=[])
    assert r.failure_code is CouncilFailureCode.NO_ELIGIBLE_LOCAL_ENGINE
    assert r.arbiter_decision.blocked is True


def test_simulator_run_with_local_provider_policy_gate_denied_blocks():
    r = run_offline_council_with_local_candidates(
        LocalCandidateRequest(prompt="x", max_candidates=2),
        DeterministicLocalCandidateProvider(),
        judge_fixtures=_judges([("A", 4), ("B", 4)]),
        gate=SimulatedPolicyGateResult(allowed=False, code="DENY", reason="teste"))
    assert r.failure_code is CouncilFailureCode.POLICY_GATE_DENIED
    assert r.arbiter_decision.blocked is True
