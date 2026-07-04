"""MC6 — Policy Gate em SPEC/DRY-RUN: toda resposta final passa pelo gate."""
import json

from nomos.council.policy_gate import (
    CouncilGateRequest,
    CouncilPolicyGateDryRun,
    FinalResponseEnvelope,
    GateFailureCode,
    run_offline_council_with_policy_gate,
)
from nomos.council.simulator import (
    OfflineCouncilInput,
    OfflineCouncilSimulator,
    SimulatedEngineFixture,
    SimulatedJudgeFixture,
)

GATE = CouncilPolicyGateDryRun()
SIM = OfflineCouncilSimulator()


def _req(**kw):
    base = dict(session_id="sess-1", risk_level="A1", has_final_content=True)
    base.update(kw)
    return CouncilGateRequest(**base)


def _offline(risk="A1", private=False, blocked=False, sensitive=False):
    cands = [SimulatedEngineFixture("fixture:a", "c0", "resposta A"),
             SimulatedEngineFixture("fixture:b", "c1", "resposta B")]
    judges = ([SimulatedJudgeFixture("fixture:j1", "A", overall=5),
               SimulatedJudgeFixture("fixture:j2", "B", overall=4)] if not blocked
              else [SimulatedJudgeFixture("fixture:j", "A", overall=5, alerts=["critical"])])
    return SIM.run(OfflineCouncilInput(prompt="oi", mode="balanced", risk_level=risk,
                   private_mode=private, contains_sensitive_data=sensitive,
                   candidate_fixtures=cands, judge_fixtures=judges))


# ---------------- request ----------------

def test_gate_request_repr_redacts_content():
    r = _req(final_content_chars=240)
    assert "final_content_chars=240" in repr(r)
    # não há campo de conteúdo bruto no request
    assert "content=" not in repr(r) or "final_content_chars" in repr(r)
    assert "raw" not in json.dumps(r.to_dict())


def test_gate_request_roundtrip_json():
    r = _req(risk_level="A2", final_content_chars=100)
    d = r.to_dict()
    assert json.loads(json.dumps(d, sort_keys=True)) == d
    assert d["schema"] == "nomos.council.gate_request.v1"


# ---------------- decisão ----------------

def test_gate_decision_defaults_dry_run_no_real_policy():
    d = GATE.evaluate(_req(risk_level="A0"))
    assert d.dry_run is True
    assert d.would_call_real_policy is False
    assert d.would_request_approval is False


def test_gate_blocks_arbiter_blocked():
    d = GATE.evaluate(_req(arbiter_blocked=True))
    assert d.allowed is False
    assert d.failure_code is GateFailureCode.GATE_ARBITER_BLOCKED


def test_gate_blocks_empty_final_content():
    d = GATE.evaluate(_req(has_final_content=False))
    assert d.allowed is False
    assert d.failure_code is GateFailureCode.GATE_EMPTY_FINAL_CONTENT


def test_gate_blocks_a6():
    d = GATE.evaluate(_req(risk_level="A6"))
    assert d.allowed is False and d.failure_code is GateFailureCode.GATE_A6_DENIED


def test_gate_blocks_human_approval_required():
    d = GATE.evaluate(_req(requires_human_approval=True))
    assert d.allowed is False
    assert d.failure_code is GateFailureCode.GATE_REQUIRES_APPROVAL
    assert d.would_request_approval is False   # dry-run: nunca pede aprovação real


def test_gate_blocks_sensitive_data():
    d = GATE.evaluate(_req(contains_sensitive_data=True))
    assert d.allowed is False
    assert d.failure_code is GateFailureCode.GATE_SENSITIVE_DATA_REQUIRES_STRICT_MODE


def test_gate_allows_a0_low_risk():
    d = GATE.evaluate(_req(risk_level="A0"))
    assert d.allowed is True and d.failure_code is None


def test_gate_allows_a1_low_risk():
    assert GATE.evaluate(_req(risk_level="A1")).allowed is True


def test_gate_allows_a2_without_sensitive_or_approval():
    assert GATE.evaluate(_req(risk_level="A2")).allowed is True


def test_gate_blocks_a3_high_risk():
    d = GATE.evaluate(_req(risk_level="A3"))
    assert d.allowed is False
    assert d.failure_code is GateFailureCode.GATE_HIGH_RISK_DRY_RUN_ONLY
    assert GATE.evaluate(_req(risk_level="A5")).allowed is False


def test_gate_decision_roundtrip_json():
    d = GATE.evaluate(_req(risk_level="A0"))
    dd = d.to_dict()
    assert json.loads(json.dumps(dd, sort_keys=True)) == dd
    assert dd["dry_run"] is True and dd["would_call_real_policy"] is False


# ---------------- envelope ----------------

def test_final_envelope_blocks_content_when_gate_denied():
    dec = GATE.evaluate(_req(risk_level="A6"))
    env = FinalResponseEnvelope(session_id="s", gate_decision=dec.to_dict(),
                                allowed=dec.allowed, content="segredo")
    assert env.blocked is True and env.content is None
    assert env.to_dict()["content"] is None


def test_final_envelope_allows_content_when_gate_allowed():
    dec = GATE.evaluate(_req(risk_level="A0"))
    env = FinalResponseEnvelope(session_id="s", gate_decision=dec.to_dict(),
                                allowed=dec.allowed, content="ola")
    assert env.allowed is True and env.blocked is False
    assert env.content == "ola"                 # preservado no atributo
    assert env.to_dict()["content"] is None     # nunca serializado


def test_final_envelope_private_mode_disables_persist():
    dec = GATE.evaluate(_req(risk_level="A0"))
    env = FinalResponseEnvelope(session_id="s", gate_decision=dec.to_dict(),
                                allowed=True, content="x", persist_allowed=False)
    assert env.persist_allowed is False


def test_final_envelope_repr_redacts_content():
    SEG = "CONTEUDO-FINAL-SECRETO"
    dec = GATE.evaluate(_req(risk_level="A0"))
    env = FinalResponseEnvelope(session_id="s", gate_decision=dec.to_dict(),
                                allowed=True, content=SEG)
    assert SEG not in repr(env)
    assert SEG not in json.dumps(env.to_dict(), ensure_ascii=False)


# ---------------- integração ----------------

def test_run_with_policy_gate_happy_path():
    env = run_offline_council_with_policy_gate(_offline(risk="A1"))
    assert env.allowed is True and env.blocked is False
    assert env.content is not None
    assert env.gate_decision["dry_run"] is True


def test_run_with_policy_gate_denied_blocks_content():
    # arbiter bloqueado (alerta crítico) ⇒ gate nega ⇒ sem conteúdo
    env = run_offline_council_with_policy_gate(_offline(blocked=True))
    assert env.allowed is False and env.blocked is True
    assert env.content is None


def test_run_with_policy_gate_private_mode_no_persist():
    env = run_offline_council_with_policy_gate(_offline(risk="A1", private=True))
    assert env.persist_allowed is False


def test_run_with_policy_gate_a6_denied():
    env = run_offline_council_with_policy_gate(_offline(risk="A6"))
    assert env.allowed is False and env.blocked is True
    assert env.content is None
    assert env.gate_decision["failure_code"] == "GATE_A6_DENIED"
