"""MC7 — audit envelope em SPEC/DRY-RUN: private mode + redação metadata-only."""
import json

from nomos.council.audit_envelope import (
    AuditEnvelopeFailureCode,
    CouncilAuditEnvelope,
    CouncilAuditEnvelopeBuilder,
    CouncilAuditEventType,
    CouncilAuditRedactionProfile,
    run_offline_council_with_audit_envelope,
)
from nomos.council.simulator import (
    OfflineCouncilInput,
    OfflineCouncilSimulator,
    SimulatedEngineFixture,
    SimulatedJudgeFixture,
)

B = CouncilAuditEnvelopeBuilder()
SIM = OfflineCouncilSimulator()
E = CouncilAuditEventType


def _offline(private=False):
    return SIM.run(OfflineCouncilInput(prompt="oi", risk_level="A1", private_mode=private,
                   candidate_fixtures=[SimulatedEngineFixture("fixture:a", "c0", "resp A"),
                                       SimulatedEngineFixture("fixture:b", "c1", "resp B")],
                   judge_fixtures=[SimulatedJudgeFixture("fixture:j1", "A", overall=5),
                                   SimulatedJudgeFixture("fixture:j2", "B", overall=4)]))


def _env(**kw):
    base = dict(event_type=E.SESSION_STARTED, session_id="s")
    base.update(kw)
    return CouncilAuditEnvelope(**base)


# ---------------- redaction profile ----------------

def test_redaction_profile_defaults_metadata_only():
    p = CouncilAuditRedactionProfile()
    assert p.metadata_only is True and p.redact_content is True
    assert p.redact_prompt is True and p.redact_engine_ids is True


def test_redaction_profile_private_mode_max_redaction():
    p = CouncilAuditRedactionProfile.for_private()
    assert p.metadata_only and p.redact_content and p.redact_engine_ids
    assert p.redact_prompt and p.redact_scores_detail is True


# ---------------- envelope ----------------

def test_audit_envelope_defaults_dry_run_no_write():
    e = _env()
    assert e.dry_run is True and e.would_write_audit is False and e.redacted is True


def test_audit_envelope_private_mode_disables_persist():
    e = _env(private_mode=True, persist_allowed=True)
    assert e.persist_allowed is False


def test_audit_envelope_rejects_real_write():
    e = _env()
    e.would_write_audit = True                      # tentativa de escrita real
    r = B.validate([e], private_mode=False)
    assert r.allowed is False
    assert r.failure_code is AuditEnvelopeFailureCode.AUDIT_ENVELOPE_REAL_WRITE_FORBIDDEN


def test_audit_envelope_rejects_unredacted():
    r = B.validate([_env(redacted=False)], private_mode=False)
    assert r.allowed is False
    assert r.failure_code is AuditEnvelopeFailureCode.AUDIT_ENVELOPE_NOT_REDACTED


def test_audit_envelope_rejects_sensitive_metadata_key_prompt():
    r = B.validate([_env(metadata={"prompt": "segredo"})], private_mode=False)
    assert r.failure_code is AuditEnvelopeFailureCode.AUDIT_ENVELOPE_SENSITIVE_METADATA


def test_audit_envelope_rejects_sensitive_metadata_key_api_key():
    r = B.validate([_env(metadata={"api_key": "abc"})], private_mode=False)
    assert r.failure_code is AuditEnvelopeFailureCode.AUDIT_ENVELOPE_SENSITIVE_METADATA


def test_audit_envelope_rejects_sensitive_metadata_value_bearer():
    r = B.validate([_env(metadata={"nota": "Bearer abc123token"})], private_mode=False)
    assert r.failure_code is AuditEnvelopeFailureCode.AUDIT_ENVELOPE_SENSITIVE_METADATA


def test_audit_envelope_repr_redacts_metadata():
    SEG = "CONTEUDO-BRUTO-SEG"
    e = _env(metadata={"content": SEG})
    assert SEG not in repr(e)
    assert SEG not in e.to_json()          # to_dict redige o valor sensível


def test_audit_envelope_roundtrip_json():
    e = _env(metadata={"candidate_count": 2})
    d = e.to_dict()
    assert json.loads(json.dumps(d, sort_keys=True)) == d
    assert d["schema"] == "nomos.council.audit_envelope.v1"
    assert d["would_write_audit"] is False


# ---------------- dry-run result ----------------

def test_audit_dry_run_result_rejects_sensitive_metadata():
    r = B.validate([_env(metadata={"secret": "x"})], private_mode=False)
    assert r.allowed is False and r.dry_run is True and r.would_write_audit is False


def test_audit_dry_run_result_rejects_private_persist():
    e = _env(private_mode=False, persist_allowed=True)   # persist=True mas validado como privado
    r = B.validate([e], private_mode=True)
    assert r.allowed is False
    assert r.failure_code is AuditEnvelopeFailureCode.AUDIT_ENVELOPE_PRIVATE_PERSIST_DENIED


# ---------------- builder ----------------

def test_audit_builder_normal_mode_metadata_only():
    r = B.build_for_result(_offline(), private_mode=False)
    assert r.allowed is True and r.dry_run is True and r.would_write_audit is False
    for e in r.envelopes:
        assert set(e.metadata.keys()) <= {"candidate_count", "review_count",
                                          "failure_code", "redaction_profile"}


def test_audit_builder_private_mode_no_persist():
    r = B.build_for_result(_offline(private=True), private_mode=True)
    assert r.allowed is True
    assert all(e.persist_allowed is False for e in r.envelopes)


def test_audit_builder_never_includes_candidate_content():
    r = B.build_for_result(_offline(), private_mode=False)
    dump = r.to_json()
    assert "resp A" not in dump and "resp B" not in dump


def test_audit_builder_never_includes_final_content():
    res = _offline()
    r = B.build_for_result(res, private_mode=False)
    assert res.arbiter_decision.final_content not in r.to_json()


def test_audit_builder_never_includes_prompt():
    # o prompt "oi" não deve aparecer como conteúdo de metadata em lugar nenhum
    r = B.build_for_result(_offline(), private_mode=False)
    for e in r.envelopes:
        assert "prompt" not in e.metadata


def test_audit_builder_counts_candidates_reviews_only():
    r = B.build_for_result(_offline(), private_mode=False)
    md = r.envelopes[0].metadata
    assert md["candidate_count"] == 2 and md["review_count"] == 2


def test_audit_builder_deterministic_same_input():
    res = _offline()
    a = B.build_for_result(res, private_mode=True).to_dict()
    b = B.build_for_result(res, private_mode=True).to_dict()
    assert a == b


# ---------------- integração ----------------

def test_run_with_audit_envelope_happy_path():
    r = run_offline_council_with_audit_envelope(_offline(), private_mode=False)
    assert r.allowed is True and r.would_write_audit is False and len(r.envelopes) >= 1


def test_run_with_audit_envelope_private_mode_no_persist():
    r = run_offline_council_with_audit_envelope(_offline(private=True))
    assert all(e.persist_allowed is False for e in r.envelopes)


def test_run_with_audit_envelope_sensitive_metadata_blocks():
    r = run_offline_council_with_audit_envelope(
        _offline(), private_mode=False, extra_metadata={"prompt": "vazou", "token": "x"})
    assert r.allowed is False
    assert r.failure_code is AuditEnvelopeFailureCode.AUDIT_ENVELOPE_SENSITIVE_METADATA
    assert "vazou" not in r.to_json()      # e mesmo bloqueado, não vaza
