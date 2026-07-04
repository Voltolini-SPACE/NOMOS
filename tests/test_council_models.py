"""MC1 — contratos dos modelos do Motor Council (data models only)."""
import pytest

from nomos.council.models import (
    AnswerCandidate,
    ArbiterDecision,
    BlindReview,
    CouncilAuditRecord,
    CouncilConfidence,
    CouncilDisagreementLevel,
    CouncilMode,
    CouncilModelError,
    CouncilPolicy,
    CouncilRiskLevel,
    CouncilSession,
    DisagreementReport,
    JudgeScore,
    RiskAssessment,
)


# ---------------- session ----------------

def test_council_session_roundtrip_json():
    s = CouncilSession(session_id="s1", mode=CouncilMode.CRITICAL,
                       risk_level=CouncilRiskLevel.A2, candidate_count=3, judge_count=3)
    back = CouncilSession.from_json(s.to_json())
    assert back == s
    assert back.to_dict()["schema"] == "nomos.council.session.v1"
    assert back.mode is CouncilMode.CRITICAL and back.risk_level is CouncilRiskLevel.A2


def test_council_session_requires_id_and_nonnegative_counts():
    with pytest.raises(CouncilModelError, match="session_id"):
        CouncilSession(session_id="", mode="fast", risk_level="A0")
    with pytest.raises(CouncilModelError, match="negativos"):
        CouncilSession(session_id="s", mode="fast", risk_level="A0", candidate_count=-1)


def test_council_paranoid_mode_forces_local_only():
    s = CouncilSession(session_id="s", mode=CouncilMode.PARANOID,
                       risk_level=CouncilRiskLevel.A2,
                       local_only=False, cloud_allowed=True)   # tentativa insegura
    assert s.local_only is True and s.cloud_allowed is False


# ---------------- policy ----------------

def test_council_policy_local_only_denies_cloud():
    p = CouncilPolicy(mode=CouncilMode.BALANCED, local_only=True, cloud_allowed=True)
    assert p.cloud_allowed is False
    assert p.allow_sensitive_data_to_cloud is False


def test_council_policy_defaults_final_gate_required():
    p = CouncilPolicy(mode=CouncilMode.BALANCED)
    assert p.require_final_policy_gate is True
    assert p.allow_sensitive_data_to_cloud is False
    assert p.persist_candidates is False and p.persist_reviews is False


def test_council_policy_paranoid_forces_no_persist_no_cloud():
    p = CouncilPolicy(mode=CouncilMode.PARANOID, cloud_allowed=True,
                      persist_candidates=True, persist_reviews=True)
    assert p.local_only and not p.cloud_allowed
    assert not p.persist_candidates and not p.persist_reviews


# ---------------- risk ----------------

def test_risk_assessment_sensitive_data_denies_cloud():
    r = RiskAssessment(risk_level=CouncilRiskLevel.A2, contains_sensitive_data=True)
    assert r.cloud_allowed is False
    assert r.cloud_denied_reason == "contains_sensitive_data"


def test_risk_assessment_reasons_must_be_strings():
    with pytest.raises(CouncilModelError, match="reasons"):
        RiskAssessment(risk_level="A0", reasons=[1, 2])


# ---------------- candidate ----------------

def test_answer_candidate_anonymized_removes_engine_id():
    c = AnswerCandidate(candidate_id="cand_1", engine_id="local:llama",
                        content="resposta")
    anon = c.anonymized(alias="A")
    assert anon.engine_id == "ANON"
    assert "local:llama" not in anon.to_json()
    assert anon.candidate_id == "A"


def test_answer_candidate_empty_content_requires_failure_code():
    from nomos.council.models import CouncilFailureCode
    with pytest.raises(CouncilModelError, match="failure_code"):
        AnswerCandidate(candidate_id="c", engine_id="e", content="")
    ok = AnswerCandidate(candidate_id="c", engine_id="e", content="",
                         failure_code=CouncilFailureCode.ENGINE_TIMEOUT)
    assert ok.failure_code is CouncilFailureCode.ENGINE_TIMEOUT


# ---------------- blind review ----------------

def test_blind_review_redacted_removes_judge_engine_id():
    r = BlindReview(review_id="r1", judge_engine_id="local:judge",
                    candidate_alias="A")
    pub = r.redacted_public()
    assert "judge_engine_id" not in pub
    assert "local:judge" not in str(pub)
    assert pub["candidate_alias"] == "A"


# ---------------- judge score ----------------

def test_judge_score_roundtrip_json():
    js = JudgeScore(candidate_alias="A", correctness=4, clarity=5, safety=5,
                    privacy=5, usefulness=4, evidence=3, hallucination_risk=1)
    back = JudgeScore.from_json(js.to_json())
    assert back == js
    assert back.to_dict()["safety"] == 5


def test_judge_score_rejects_out_of_range_scores():
    with pytest.raises(CouncilModelError, match="0–5"):
        JudgeScore(candidate_alias="A", correctness=9, clarity=5, safety=5,
                   privacy=5, usefulness=4, evidence=3, hallucination_risk=1)
    with pytest.raises(CouncilModelError, match="0–5"):
        JudgeScore(candidate_alias="A", correctness=-1, clarity=5, safety=5,
                   privacy=5, usefulness=4, evidence=3, hallucination_risk=1)


def test_judge_score_rejects_non_int():
    with pytest.raises(CouncilModelError, match="inteiro"):
        JudgeScore(candidate_alias="A", correctness="5", clarity=5, safety=5,
                   privacy=5, usefulness=4, evidence=3, hallucination_risk=1)


# ---------------- arbiter ----------------

def test_arbiter_decision_requires_policy_gate_by_default():
    a = ArbiterDecision(decision_id="d1", selected_candidate_alias="B",
                        final_content="ok")
    assert a.requires_policy_gate is True
    assert a.confidence is CouncilConfidence.MEDIUM


def test_arbiter_blocked_allows_empty_content():
    a = ArbiterDecision(decision_id="d", blocked=True, final_content="")
    assert a.blocked is True
    with pytest.raises(CouncilModelError, match="blocked=True"):
        ArbiterDecision(decision_id="d", blocked=False, final_content="")


# ---------------- disagreement ----------------

def test_disagreement_high_requires_clarification():
    d = DisagreementReport(level=CouncilDisagreementLevel.HIGH)
    assert d.requires_clarification is True
    low = DisagreementReport(level=CouncilDisagreementLevel.LOW)
    assert low.requires_clarification is False


# ---------------- audit record ----------------

def test_council_audit_private_mode_disables_persist():
    a = CouncilAuditRecord(session_id="s", event_type="council.session",
                           private_mode=True)
    assert a.persist_allowed is False
    b = CouncilAuditRecord(session_id="s", event_type="council.session",
                           private_mode=False)
    assert b.persist_allowed is True


# ---------------- schema / enum ----------------

def test_invalid_schema_rejected():
    with pytest.raises(CouncilModelError, match="schema inválido"):
        CouncilSession.from_dict({"schema": "wrong", "session_id": "s",
                                  "mode": "fast", "risk_level": "A0"})


def test_invalid_enum_rejected():
    with pytest.raises(CouncilModelError, match="mode inválido"):
        CouncilSession(session_id="s", mode="telepatia", risk_level="A0")
    with pytest.raises(CouncilModelError, match="risk_level inválido"):
        RiskAssessment(risk_level="Z9")
