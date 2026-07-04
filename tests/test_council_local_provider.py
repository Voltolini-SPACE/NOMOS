"""MC3 — contratos do provedor de candidatos locais do Motor Council."""
import pytest

from nomos.council.local_provider import (
    DeterministicLocalCandidateProvider,
    LocalCandidateRequest,
    LocalCandidateResult,
    LocalEngineDescriptor,
    LocalProviderError,
    run_offline_council_with_local_provider,
)
from nomos.council.models import CouncilFailureCode
from nomos.council.simulator import SimulatedJudgeFixture, SimulatedPolicyGateResult

P = DeterministicLocalCandidateProvider


def _judges(pairs):
    return [SimulatedJudgeFixture(f"fixture:j{i}", a, overall=o)
            for i, (a, o) in enumerate(pairs)]


# ---------------- descriptor ----------------

def test_local_engine_descriptor_requires_local_prefix():
    with pytest.raises(LocalProviderError, match="local:"):
        LocalEngineDescriptor(engine_id="remote:x")


def test_local_engine_descriptor_rejects_cloud():
    assert LocalEngineDescriptor("local:x", cloud=True).is_eligible is False


def test_local_engine_descriptor_rejects_network_required():
    assert LocalEngineDescriptor("local:x", network_required=True).is_eligible is False


def test_local_engine_descriptor_rejects_non_local_only():
    assert LocalEngineDescriptor("local:x", local_only=False).is_eligible is False


# ---------------- request ----------------

def test_local_candidate_request_requires_prompt():
    with pytest.raises(LocalProviderError, match="prompt"):
        LocalCandidateRequest(prompt="")


def test_local_candidate_request_rejects_zero_candidates():
    with pytest.raises(LocalProviderError, match="max_candidates"):
        LocalCandidateRequest(prompt="x", max_candidates=0)


def test_local_candidate_request_repr_redacts_prompt():
    SEG = "PROMPT-XYZ-SEG"
    req = LocalCandidateRequest(prompt=SEG)
    assert SEG not in repr(req)
    assert SEG not in str(req.to_dict())      # to_dict não inclui o prompt
    assert req.cloud_allowed is False


# ---------------- provider ----------------

def test_local_provider_lists_only_local_engines():
    for e in P().list_engines():
        assert e.engine_id.startswith("local:")


def test_local_provider_generates_answer_candidates():
    res = P().generate(LocalCandidateRequest(prompt="oi", max_candidates=2))
    assert res.failure_code is None and len(res.candidates) == 2
    for c in res.candidates:
        assert c.engine_id.startswith("local:") and c.content


def test_local_provider_limits_max_candidates():
    engines = [LocalEngineDescriptor(f"local:m{i}") for i in range(5)]
    res = P(engines).generate(LocalCandidateRequest(prompt="x", max_candidates=2))
    assert len(res.candidates) == 2


def test_local_provider_fails_closed_without_eligible_engine():
    res = P([]).generate(LocalCandidateRequest(prompt="x"))
    assert res.candidates == []
    assert res.failure_code is CouncilFailureCode.NO_ELIGIBLE_LOCAL_ENGINE


def test_local_provider_fails_closed_for_cloud_engine():
    res = P([LocalEngineDescriptor("local:x", cloud=True)]).generate(
        LocalCandidateRequest(prompt="x"))
    assert res.candidates == []
    assert res.failure_code is CouncilFailureCode.CLOUD_BLOCKED_BY_LOCAL_LOCK


def test_local_provider_fails_closed_for_network_engine():
    res = P([LocalEngineDescriptor("local:x", network_required=True)]).generate(
        LocalCandidateRequest(prompt="x"))
    assert res.candidates == []
    assert res.failure_code in {CouncilFailureCode.CLOUD_BLOCKED_BY_LOCAL_LOCK,
                                CouncilFailureCode.ENGINE_FAILED}


def test_local_provider_fails_closed_for_non_local_engine():
    res = P([LocalEngineDescriptor("local:x", local_only=False)]).generate(
        LocalCandidateRequest(prompt="x"))
    assert res.candidates == []
    assert res.failure_code is CouncilFailureCode.NO_ELIGIBLE_LOCAL_ENGINE


def test_local_provider_sensitive_data_requires_capable_engine():
    # engine incapaz de dado sensível ⇒ recusa
    res = P([LocalEngineDescriptor("local:x", supports_sensitive_data=False)]).generate(
        LocalCandidateRequest(prompt="x", contains_sensitive_data=True))
    assert res.candidates == []
    assert res.failure_code is CouncilFailureCode.SENSITIVE_DATA_CLOUD_DENIED
    # engine capaz ⇒ funciona
    ok = P([LocalEngineDescriptor("local:x", supports_sensitive_data=True)]).generate(
        LocalCandidateRequest(prompt="x", contains_sensitive_data=True))
    assert ok.failure_code is None and ok.candidates


def test_local_provider_paranoid_mode_local_only():
    req = LocalCandidateRequest(prompt="x", mode="paranoid")
    assert req.local_only is True and req.cloud_allowed is False
    res = P().generate(req)
    for c in res.candidates:
        assert c.engine_id.startswith("local:")


def test_local_provider_private_mode_does_not_persist_prompt():
    SEG = "PROMPT-PRIVADO-1"
    res = P().generate(LocalCandidateRequest(prompt=SEG, private_mode=True))
    import json
    assert SEG not in json.dumps(res.to_dict(), ensure_ascii=False)


def test_local_provider_result_repr_redacts_prompt_and_content():
    SEG = "PROMPT-SECRETO"
    res = P().generate(LocalCandidateRequest(prompt=SEG))
    r = repr(res)
    assert SEG not in r
    # conteúdo integral dos candidatos não aparece no repr do resultado
    for c in res.candidates:
        assert c.content not in r
    assert isinstance(res, LocalCandidateResult)


# ---------------- integração com o simulador ----------------

def test_simulator_run_with_local_provider_happy_path():
    r = run_offline_council_with_local_provider(
        LocalCandidateRequest(prompt="oi", max_candidates=2), P(),
        judge_fixtures=_judges([("A", 5), ("B", 4)]))
    assert r.failure_code is None
    assert r.arbiter_decision.blocked is False
    assert r.policy_gate_result.allowed is True
    assert all(c.engine_id == "ANON" for c in r.anonymized_candidates)


def test_simulator_run_with_local_provider_no_engine_fails_closed():
    r = run_offline_council_with_local_provider(
        LocalCandidateRequest(prompt="x"), P([]), judge_fixtures=[])
    assert r.failure_code is CouncilFailureCode.NO_ELIGIBLE_LOCAL_ENGINE
    assert r.arbiter_decision.blocked is True


def test_simulator_run_with_local_provider_policy_gate_denied_blocks():
    r = run_offline_council_with_local_provider(
        LocalCandidateRequest(prompt="x", max_candidates=2), P(),
        judge_fixtures=_judges([("A", 4), ("B", 4)]),
        gate=SimulatedPolicyGateResult(allowed=False, code="DENY", reason="t"))
    assert r.failure_code is CouncilFailureCode.POLICY_GATE_DENIED
    assert r.arbiter_decision.blocked is True


def test_local_provider_deterministic_same_input_same_output():
    req = LocalCandidateRequest(prompt="det", max_candidates=2)
    a = run_offline_council_with_local_provider(req, P(), _judges([("A", 5), ("B", 4)])).to_json()
    b = run_offline_council_with_local_provider(req, P(), _judges([("A", 5), ("B", 4)])).to_json()
    assert a == b


def test_local_provider_run_time_returns_offline_result():
    r = run_offline_council_with_local_provider(
        LocalCandidateRequest(prompt="x", max_candidates=1), P(),
        judge_fixtures=_judges([("A", 4)]))
    assert r.candidates and r.candidates[0].engine_id.startswith("local:")
