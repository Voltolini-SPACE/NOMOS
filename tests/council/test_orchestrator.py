"""MC8 — orquestrador em SPEC/DRY-RUN: compõe provider -> simulador -> gate ->
audit envelope, provando ordem determinística e comportamento fail-closed."""
import json

import pytest

from nomos.council.audit_envelope import AuditEnvelopeFailureCode, CouncilAuditDryRunResult
from nomos.council.local_provider import (
    DeterministicLocalCandidateProvider,
    LocalCandidateRequest,
    LocalEngineDescriptor,
)
from nomos.council.orchestrator import (
    CouncilOrchestrationInput,
    CouncilOrchestrationStep,
    CouncilOrchestrationStepName,
    CouncilOrchestrationTrace,
    CouncilOrchestratorDryRun,
    OrchestrationFailureCode,
    OrchestratorError,
    _verificar_dry_run_only,
    _verificar_persist_privado,
)

ORCH = CouncilOrchestratorDryRun()

_ORDEM_BASE = ["INPUT_VALIDATED", "LOCAL_PROVIDER_EVALUATED", "CANDIDATES_CREATED",
              "SIMULATOR_RAN", "POLICY_GATE_EVALUATED", "FINAL_ENVELOPE_CREATED",
              "AUDIT_ENVELOPE_CREATED"]


def _entrada(**kw):
    base = dict(session_id="sess-orch-1", prompt="qual a capital da frança?")
    base.update(kw)
    return CouncilOrchestrationInput(**base)


def _nomes(resultado):
    return [s["name"] for s in resultado.trace["steps"]]


# ---------------- CouncilOrchestrationInput ----------------

def test_orchestration_input_repr_redacts_prompt():
    SEG = "PROMPT-ULTRASSECRETO-777"
    entrada = _entrada(prompt=SEG)
    assert SEG not in repr(entrada)
    assert f"{len(SEG)} chars" in repr(entrada)


def test_orchestration_input_roundtrip_json():
    entrada = _entrada(risk_level="A2", max_candidates=3)
    d = entrada.to_dict()
    assert json.loads(json.dumps(d, sort_keys=True)) == d
    assert d["schema"] == "nomos.council.orchestration_input.v1"
    assert "prompt" not in d
    assert d["prompt_chars"] == len(entrada.prompt)
    assert json.loads(entrada.to_json()) == d


# ---------------- CouncilOrchestrationTrace ----------------

def test_orchestration_trace_defaults_dry_run_redacted():
    t = CouncilOrchestrationTrace()
    assert t.dry_run is True and t.redacted is True and t.private_mode is False
    assert t.steps == []


def test_orchestration_trace_roundtrip_json():
    t = CouncilOrchestrationTrace(steps=[CouncilOrchestrationStep(
        name=CouncilOrchestrationStepName.INPUT_VALIDATED, metadata={"mode": "balanced"})])
    d = t.to_dict()
    assert json.loads(json.dumps(d, sort_keys=True)) == d
    assert d["schema"] == "nomos.council.orchestration_trace.v1"


# ---------------- CouncilOrchestrationStep ----------------

def test_orchestration_step_rejects_sensitive_metadata():
    with pytest.raises(OrchestratorError):
        CouncilOrchestrationStep(name=CouncilOrchestrationStepName.INPUT_VALIDATED,
                                 metadata={"prompt": "vazou"})
    with pytest.raises(OrchestratorError):
        CouncilOrchestrationStep(name=CouncilOrchestrationStepName.INPUT_VALIDATED,
                                 metadata={"nota": "Bearer abc123token"})


def test_orchestration_step_roundtrip_json():
    s = CouncilOrchestrationStep(name=CouncilOrchestrationStepName.CANDIDATES_CREATED,
                                 metadata={"candidate_count": 2})
    d = s.to_dict()
    assert json.loads(json.dumps(d, sort_keys=True)) == d
    assert d["schema"] == "nomos.council.orchestration_step.v1"
    assert d["name"] == "CANDIDATES_CREATED"


# ---------------- comportamentos obrigatórios ----------------

def test_orchestrator_happy_path_a1_allowed():
    r = ORCH.run(_entrada(mode="balanced", risk_level="A1"))
    assert r.allowed is True and r.blocked is False
    assert r.dry_run is True and r.would_execute is False and r.would_write_audit is False
    assert _nomes(r) == _ORDEM_BASE + ["ORCHESTRATION_COMPLETED"]


def test_orchestrator_a6_denied():
    r = ORCH.run(_entrada(risk_level="A6"))
    assert r.allowed is False and r.blocked is True
    assert r.failure_code == OrchestrationFailureCode.ORCH_POLICY_GATE_DENIED
    assert r.final_envelope["content"] is None


def test_orchestrator_sensitive_data_denied():
    entrada = _entrada(contains_sensitive_data=True)
    r = ORCH.run(entrada)
    assert r.blocked is True
    assert r.failure_code == OrchestrationFailureCode.ORCH_POLICY_GATE_DENIED
    assert r.final_envelope["content"] is None
    # nunca cloud: o contrato do provider local nega cloud mesmo p/ dado sensível
    req = LocalCandidateRequest(prompt=entrada.prompt, contains_sensitive_data=True)
    assert req.cloud_allowed is False


def test_orchestrator_private_mode_no_persist_anywhere():
    r = ORCH.run(_entrada(private_mode=True))
    assert r.final_envelope["persist_allowed"] is False
    assert len(r.audit_result["envelopes"]) >= 1
    assert all(e["persist_allowed"] is False for e in r.audit_result["envelopes"])
    assert r.trace["redacted"] is True and r.trace["private_mode"] is True


def test_orchestrator_no_candidates_fails_closed():
    orch_vazio = CouncilOrchestratorDryRun(
        provider=DeterministicLocalCandidateProvider(engines=[]))
    r = orch_vazio.run(_entrada())
    assert r.blocked is True
    assert r.failure_code in (OrchestrationFailureCode.ORCH_PROVIDER_FAILED,
                              OrchestrationFailureCode.ORCH_NO_CANDIDATES)
    assert _nomes(r) == _ORDEM_BASE + ["ORCHESTRATION_BLOCKED"]
    gate_step = next(s for s in r.trace["steps"] if s["name"] == "POLICY_GATE_EVALUATED")
    assert gate_step["metadata"]["gate_allowed"] is False


def test_orchestrator_gate_denied_removes_content():
    r = ORCH.run(_entrada(risk_level="A6"))
    assert r.final_envelope["content"] is None
    assert r.final_envelope["allowed"] is False
    assert r.final_envelope["blocked"] is True


def test_orchestrator_audit_denied_blocks_result():
    class BuilderNega:
        def build_for_result(self, result, private_mode, extra_metadata=None):
            return CouncilAuditDryRunResult(
                allowed=False, envelopes=[],
                failure_code=AuditEnvelopeFailureCode.AUDIT_ENVELOPE_SENSITIVE_METADATA)
    orch = CouncilOrchestratorDryRun(audit_builder=BuilderNega())
    r = orch.run(_entrada())
    assert r.allowed is False and r.blocked is True
    assert r.failure_code == OrchestrationFailureCode.ORCH_AUDIT_ENVELOPE_DENIED


def test_orchestrator_trace_order_happy_path():
    r = ORCH.run(_entrada())
    assert _nomes(r) == _ORDEM_BASE + ["ORCHESTRATION_COMPLETED"]


def test_orchestrator_trace_order_when_blocked():
    r = ORCH.run(_entrada(risk_level="A6"))
    nomes = _nomes(r)
    assert nomes == _ORDEM_BASE + ["ORCHESTRATION_BLOCKED"]
    assert "POLICY_GATE_EVALUATED" in nomes
    assert "FINAL_ENVELOPE_CREATED" in nomes
    assert "AUDIT_ENVELOPE_CREATED" in nomes


def test_orchestrator_policy_gate_before_final_envelope():
    for entrada in (_entrada(), _entrada(risk_level="A6"), _entrada(contains_sensitive_data=True)):
        nomes = _nomes(ORCH.run(entrada))
        assert nomes.index("POLICY_GATE_EVALUATED") < nomes.index("FINAL_ENVELOPE_CREATED")


def test_orchestrator_audit_after_gate():
    for entrada in (_entrada(), _entrada(risk_level="A6")):
        nomes = _nomes(ORCH.run(entrada))
        assert nomes.index("POLICY_GATE_EVALUATED") < nomes.index("AUDIT_ENVELOPE_CREATED")
        assert nomes.index("FINAL_ENVELOPE_CREATED") < nomes.index("AUDIT_ENVELOPE_CREATED")


def test_orchestrator_never_would_execute():
    for entrada in (_entrada(), _entrada(risk_level="A6"), _entrada(private_mode=True)):
        assert ORCH.run(entrada).would_execute is False


def test_orchestrator_never_would_write_audit():
    for entrada in (_entrada(), _entrada(risk_level="A6"), _entrada(private_mode=True)):
        assert ORCH.run(entrada).would_write_audit is False


def test_orchestrator_deterministic_same_input():
    a = ORCH.run(_entrada(session_id="sess-det")).to_dict()
    b = ORCH.run(_entrada(session_id="sess-det")).to_dict()
    assert a == b


def test_orchestrator_result_roundtrip_json():
    r = ORCH.run(_entrada())
    d = r.to_dict()
    assert json.loads(json.dumps(d, sort_keys=True)) == d
    assert d["schema"] == "nomos.council.orchestration_result.v1"


def test_orchestrator_result_repr_redacts_content():
    r = ORCH.run(_entrada())
    rep = repr(r)
    assert "final_envelope" not in rep
    assert "audit_result" not in rep
    assert "trace" not in rep
    assert "[simulado]" not in rep


def test_orchestrator_no_prompt_in_to_json():
    SEG = "PERGUNTA-CONFIDENCIAL-999"
    r = ORCH.run(_entrada(prompt=SEG))
    assert SEG not in r.to_json()


def test_orchestrator_no_candidate_content_in_trace():
    r = ORCH.run(_entrada())
    dump = json.dumps(r.trace, ensure_ascii=False)
    assert "[dry-run] resposta local simulada" not in dump


def test_orchestrator_no_final_content_in_trace():
    r = ORCH.run(_entrada())
    dump = json.dumps(r.trace, ensure_ascii=False)
    assert "[simulado] resposta do candidato" not in dump


def test_orchestrator_no_engine_ids_in_private_mode_trace():
    r = ORCH.run(_entrada(private_mode=True))
    dump = json.dumps(r.trace, ensure_ascii=False)
    assert "local:mock-a" not in dump
    assert "local:mock-b" not in dump


def test_orchestrator_private_mode_audit_envelopes_no_persist():
    r = ORCH.run(_entrada(private_mode=True))
    assert len(r.audit_result["envelopes"]) >= 1
    assert all(e["persist_allowed"] is False for e in r.audit_result["envelopes"])


# ---------------- comportamentos extras (robustez / defesa em profundidade) ----------------

def test_orchestrator_input_invalid_after_tampering_fails_closed():
    entrada = _entrada()
    entrada.session_id = ""              # mutação pós-construção (bypassa o __post_init__)
    r = CouncilOrchestratorDryRun().run(entrada)
    assert r.blocked is True
    assert r.failure_code == OrchestrationFailureCode.ORCH_INPUT_INVALID
    assert _nomes(r) == ["INPUT_VALIDATED", "ORCHESTRATION_BLOCKED"]


def test_orchestrator_provider_cloud_engine_maps_provider_failed():
    prov = DeterministicLocalCandidateProvider(
        engines=[LocalEngineDescriptor(engine_id="local:bad", cloud=True)])
    r = CouncilOrchestratorDryRun(provider=prov).run(_entrada())
    assert r.failure_code == OrchestrationFailureCode.ORCH_PROVIDER_FAILED


def test_orchestrator_provider_exception_maps_provider_failed():
    class ProviderQuebrado:
        def list_engines(self):
            return []

        def generate(self, request):
            raise RuntimeError("boom")
    r = CouncilOrchestratorDryRun(provider=ProviderQuebrado()).run(_entrada())
    assert r.blocked is True
    assert r.failure_code == OrchestrationFailureCode.ORCH_PROVIDER_FAILED


def test_orchestrator_gate_exception_maps_internal_invariant():
    class GateQuebrado:
        def evaluate(self, request):
            raise RuntimeError("gate boom")
    r = CouncilOrchestratorDryRun(gate=GateQuebrado()).run(_entrada())
    assert r.blocked is True
    assert r.failure_code == OrchestrationFailureCode.ORCH_INTERNAL_INVARIANT_FAILED
    assert _nomes(r) == _ORDEM_BASE + ["ORCHESTRATION_BLOCKED"]


def test_orchestrator_audit_exception_maps_internal_invariant():
    class BuilderQuebrado:
        def build_for_result(self, result, private_mode, extra_metadata=None):
            raise RuntimeError("audit boom")
    r = CouncilOrchestratorDryRun(audit_builder=BuilderQuebrado()).run(_entrada())
    assert r.blocked is True
    assert r.failure_code == OrchestrationFailureCode.ORCH_INTERNAL_INVARIANT_FAILED


def test_orchestrator_simulator_exception_maps_simulator_failed():
    class SimuladorQuebrado:
        def run_with_candidates(self, **kw):
            raise RuntimeError("sim boom")
    r = CouncilOrchestratorDryRun(simulator=SimuladorQuebrado()).run(_entrada())
    assert r.blocked is True
    assert r.failure_code == OrchestrationFailureCode.ORCH_SIMULATOR_FAILED


def test_orchestrator_persist_privado_helper_direct():
    class FakeEnvelope:
        persist_allowed = True

    class FakeAuditResult:
        envelopes = []
    falha = _verificar_persist_privado(True, FakeEnvelope(), FakeAuditResult())
    assert falha is not None
    assert falha.code == OrchestrationFailureCode.ORCH_PRIVATE_MODE_PERSIST_DENIED
    assert _verificar_persist_privado(False, FakeEnvelope(), FakeAuditResult()) is None


def test_orchestrator_dry_run_only_helper_direct():
    class FakeResultado:
        would_execute = True
        would_write_audit = False
        dry_run = True
    falha = _verificar_dry_run_only(FakeResultado())
    assert falha is not None
    assert falha.code == OrchestrationFailureCode.ORCH_DRY_RUN_ONLY

    class FakeResultadoOk:
        would_execute = False
        would_write_audit = False
        dry_run = True
    assert _verificar_dry_run_only(FakeResultadoOk()) is None


def test_orchestrator_paranoid_mode_recorded_local_only():
    r = ORCH.run(_entrada(mode="paranoid"))
    passo = r.trace["steps"][0]
    assert passo["name"] == "INPUT_VALIDATED"
    assert passo["metadata"]["local_only"] is True
    assert passo["metadata"]["mode"] == "paranoid"


def test_orchestrator_constructor_defaults_are_dry_run_components():
    orch = CouncilOrchestratorDryRun()
    from nomos.council.local_adapter import DryRunAdapterCandidateProvider
    assert isinstance(orch._provider, DryRunAdapterCandidateProvider)


def test_orchestrator_provider_returns_empty_candidates_without_failure_code():
    class ProviderVazioSemCodigo:
        def list_engines(self):
            return [LocalEngineDescriptor(engine_id="local:mock-a")]

        def generate(self, request):
            from nomos.council.local_provider import LocalCandidateResult
            return LocalCandidateResult(candidates=[], failure_code=None)
    r = CouncilOrchestratorDryRun(provider=ProviderVazioSemCodigo()).run(_entrada())
    assert r.blocked is True
    assert r.failure_code == OrchestrationFailureCode.ORCH_NO_CANDIDATES


def test_orchestrator_provider_list_engines_raises_defaults_zero():
    class ProviderListEnginesQuebrado:
        def list_engines(self):
            raise RuntimeError("list boom")

        def generate(self, request):
            from nomos.council.local_provider import LocalCandidateResult
            return LocalCandidateResult(candidates=[], failure_code=None)
    r = CouncilOrchestratorDryRun(provider=ProviderListEnginesQuebrado()).run(_entrada())
    passo = next(s for s in r.trace["steps"] if s["name"] == "LOCAL_PROVIDER_EVALUATED")
    assert passo["metadata"]["engine_count"] == 0


def test_orchestration_input_rejects_invalid_construction():
    with pytest.raises(OrchestratorError):
        CouncilOrchestrationInput(session_id="", prompt="oi")
    with pytest.raises(OrchestratorError):
        CouncilOrchestrationInput(session_id="s", prompt="")
    with pytest.raises(OrchestratorError):
        CouncilOrchestrationInput(session_id="s", prompt="oi", max_candidates=0)


def test_orchestration_input_local_only_always_true():
    assert _entrada(mode="paranoid").local_only is True
    assert _entrada(mode="fast").local_only is True


def test_orchestration_step_to_json_and_repr():
    s = CouncilOrchestrationStep(name=CouncilOrchestrationStepName.SIMULATOR_RAN,
                                 metadata={"review_count": 2})
    assert json.loads(s.to_json())["name"] == "SIMULATOR_RAN"
    assert "SIMULATOR_RAN" in repr(s)
    assert "review_count" in repr(s)   # só a chave, nunca o valor bruto de conteúdo


def test_orchestration_trace_to_json_and_repr():
    t = CouncilOrchestrationTrace(steps=[
        CouncilOrchestrationStep(name=CouncilOrchestrationStepName.INPUT_VALIDATED)])
    assert json.loads(t.to_json())["schema"] == "nomos.council.orchestration_trace.v1"
    assert "INPUT_VALIDATED" in repr(t)
