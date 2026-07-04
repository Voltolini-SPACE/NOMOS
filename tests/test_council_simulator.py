"""MC2 — contratos do simulador offline do Motor Council."""
import pytest

from nomos.council.models import (
    CouncilDisagreementLevel,
    CouncilFailureCode,
)
from nomos.council.simulator import (
    OfflineCouncilInput,
    OfflineCouncilResult,
    OfflineCouncilSimulator,
    SimulatedEngineFixture,
    SimulatedJudgeFixture,
    SimulatedPolicyGateResult,
    SimulatorError,
)

SIM = OfflineCouncilSimulator()


def _cands(n=2):
    return [SimulatedEngineFixture(f"fixture:e{i}", f"cand_{i}", f"resposta {i}")
            for i in range(n)]


def _judges(pairs):
    # pairs: [(alias, overall), ...]
    return [SimulatedJudgeFixture(f"fixture:j{i}", a, overall=o)
            for i, (a, o) in enumerate(pairs)]


def test_simulator_balanced_happy_path():
    r = SIM.run(OfflineCouncilInput(prompt="oi", mode="balanced", risk_level="A1",
                candidate_fixtures=_cands(2),
                judge_fixtures=_judges([("A", 5), ("B", 4)])))
    assert r.failure_code is None
    assert r.arbiter_decision.blocked is False
    assert r.arbiter_decision.requires_policy_gate is True
    assert r.policy_gate_result.allowed is True


def test_simulator_paranoid_forces_local_only():
    r = SIM.run(OfflineCouncilInput(prompt="x", mode="paranoid",
                local_only=False, candidate_fixtures=_cands(1),
                judge_fixtures=_judges([("A", 4)])))
    assert r.session.local_only is True
    assert r.policy.cloud_allowed is False


def test_simulator_sensitive_data_denies_cloud():
    r = SIM.run(OfflineCouncilInput(prompt="x", contains_sensitive_data=True,
                candidate_fixtures=_cands(1), judge_fixtures=_judges([("A", 4)])))
    assert r.risk.cloud_denied_reason is not None
    assert r.policy.cloud_allowed is False


def test_simulator_no_candidates_fails_closed():
    r = SIM.run(OfflineCouncilInput(prompt="x", candidate_fixtures=[]))
    assert r.failure_code is CouncilFailureCode.NO_ELIGIBLE_LOCAL_ENGINE
    assert r.arbiter_decision.blocked is True


def test_simulator_policy_gate_denied_blocks():
    r = SIM.run(OfflineCouncilInput(prompt="x", candidate_fixtures=_cands(2),
                judge_fixtures=_judges([("A", 4), ("B", 4)]),
                gate=SimulatedPolicyGateResult(allowed=False, code="DENY_SIM",
                                               reason="teste")))
    assert r.failure_code is CouncilFailureCode.POLICY_GATE_DENIED
    assert r.arbiter_decision.blocked is True


def test_simulator_high_disagreement_blocks_or_clarifies():
    r = SIM.run(OfflineCouncilInput(prompt="x", candidate_fixtures=_cands(1),
                judge_fixtures=_judges([("A", 5), ("A", 1)])))
    assert r.disagreement.level is CouncilDisagreementLevel.HIGH
    assert r.disagreement.requires_clarification is True
    assert r.arbiter_decision.blocked is True


def test_simulator_private_mode_disables_audit_persistence():
    r = SIM.run(OfflineCouncilInput(prompt="x", private_mode=True,
                candidate_fixtures=_cands(1), judge_fixtures=_judges([("A", 4)])))
    assert all(a.persist_allowed is False for a in r.audit_records)
    assert r.policy.persist_candidates is False and r.policy.persist_reviews is False


def test_simulator_anonymized_candidates_remove_engine_id():
    r = SIM.run(OfflineCouncilInput(prompt="x", candidate_fixtures=_cands(2),
                judge_fixtures=_judges([("A", 4), ("B", 4)])))
    assert r.anonymized_candidates
    for c in r.anonymized_candidates:
        assert c.engine_id == "ANON"
    assert "fixture:" not in r.to_json().split('"anonymized_candidates"')[1][:400]


def test_simulator_self_judging_excluded_when_possible():
    # juiz j0 é o mesmo engine do candidato alias A (fixture:e0); há juiz limpo (j-clean)
    cands = _cands(2)  # cand_0 -> alias A (fixture:e0), cand_1 -> alias B (fixture:e1)
    judges = [SimulatedJudgeFixture("fixture:e0", "A", overall=5),   # autojulgamento
              SimulatedJudgeFixture("fixture:jx", "B", overall=4)]   # juiz limpo
    r = SIM.run(OfflineCouncilInput(prompt="x", candidate_fixtures=cands,
                judge_fixtures=judges))
    # a review de autojulgamento foi excluída
    engines = {rev.judge_engine_id for rev in r.reviews}
    assert "fixture:e0" not in engines
    assert r.failure_code is None


def test_simulator_insufficient_judges_warns_or_fails_closed():
    # único juiz é autor do único candidato ⇒ conflito total ⇒ fail-closed
    cands = _cands(1)  # cand_0 -> alias A (fixture:e0)
    judges = [SimulatedJudgeFixture("fixture:e0", "A", overall=5)]
    r = SIM.run(OfflineCouncilInput(prompt="x", candidate_fixtures=cands,
                judge_fixtures=judges))
    assert r.failure_code is CouncilFailureCode.INSUFFICIENT_JUDGES
    assert r.arbiter_decision.blocked is True


def test_simulator_critical_alert_blocks():
    r = SIM.run(OfflineCouncilInput(prompt="x", candidate_fixtures=_cands(1),
                judge_fixtures=[SimulatedJudgeFixture("fixture:j", "A", overall=4,
                                                      alerts=["critical"])]))
    assert r.failure_code is CouncilFailureCode.ARBITER_UNSAFE_OUTPUT
    assert r.arbiter_decision.blocked is True


def test_simulator_engine_failure_returns_failure_code():
    fx = SimulatedEngineFixture("fixture:a", "cand_a", content="",
                                failure_code=CouncilFailureCode.ENGINE_FAILED)
    r = SIM.run(OfflineCouncilInput(prompt="x", candidate_fixtures=[fx]))
    assert r.failure_code is CouncilFailureCode.ENGINE_FAILED
    assert r.arbiter_decision.blocked is True


def test_simulator_council_disabled():
    r = SIM.run(OfflineCouncilInput(prompt="x", council_enabled=False,
                candidate_fixtures=_cands(1), judge_fixtures=_judges([("A", 4)])))
    assert r.failure_code is CouncilFailureCode.COUNCIL_DISABLED


def test_simulator_result_roundtrip_json():
    r = SIM.run(OfflineCouncilInput(prompt="x", candidate_fixtures=_cands(2),
                judge_fixtures=_judges([("A", 4), ("B", 4)])))
    import json
    d = json.loads(r.to_json())
    assert d["schema"] == "nomos.council.offline_result.v1"
    assert d["failure_code"] is None
    assert len(d["candidates"]) == 2


def test_simulator_deterministic_same_input_same_output():
    inp = OfflineCouncilInput(prompt="determinismo", candidate_fixtures=_cands(3),
                              judge_fixtures=_judges([("A", 5), ("B", 4), ("C", 4)]))
    a = SIM.run(inp).to_json()
    b = SIM.run(inp).to_json()
    assert a == b


def test_simulator_engine_fixture_requires_prefix():
    with pytest.raises(SimulatorError, match="fixture:"):
        SimulatedEngineFixture("local:real", "cand", "x")
    with pytest.raises(SimulatorError, match="fixture:"):
        SimulatedJudgeFixture("local:real", "A", overall=4)


def test_simulator_result_is_offline_result_type():
    r = SIM.run(OfflineCouncilInput(prompt="x", candidate_fixtures=_cands(1),
                judge_fixtures=_judges([("A", 4)])))
    assert isinstance(r, OfflineCouncilResult)
