"""NOMOS Motor Council — Fase MC1 (data models only).

Este pacote contém APENAS modelos de dados puros (stdlib) para o Motor Council,
conforme docs/architecture/MOTOR_COUNCIL_SPEC_v1.md. Não executa motores, não faz
I/O, não persiste, não acessa rede, não integra policy/audit/vault reais. As
invariantes de segurança são impostas por construção (fail-closed):

- local_only  ⇒ cloud_allowed = False
- paranoid    ⇒ local_only = True e cloud_allowed = False
- private_mode ⇒ persist_allowed = False
- dado sensível ⇒ cloud negada (representada)

A execução real virá em fases posteriores (MC2+), sempre sob o mesmo gate A0–A6.
"""
from nomos.council.models import (
    AnswerCandidate,
    ArbiterDecision,
    BlindReview,
    CouncilAuditRecord,
    CouncilConfidence,
    CouncilDisagreementLevel,
    CouncilFailureCode,
    CouncilMode,
    CouncilModelError,
    CouncilPolicy,
    CouncilRiskLevel,
    CouncilSession,
    DisagreementReport,
    JudgeScore,
    RiskAssessment,
)

from nomos.council.audit_envelope import (
    AuditEnvelopeError,
    AuditEnvelopeFailureCode,
    CouncilAuditDryRunResult,
    CouncilAuditEnvelope,
    CouncilAuditEnvelopeBuilder,
    CouncilAuditEnvelopeFailure,
    CouncilAuditEventType,
    CouncilAuditRedactionProfile,
    run_offline_council_with_audit_envelope,
)
from nomos.council.policy_gate import (
    CouncilGateDecision,
    CouncilGateFailure,
    CouncilGateRequest,
    CouncilGateRisk,
    CouncilPolicyGateDryRun,
    FinalResponseEnvelope,
    GateError,
    GateFailureCode,
    gate_risk_of,
    run_offline_council_with_policy_gate,
)
from nomos.council.local_harness import (
    REAL_LOCAL_ENGINE_EXECUTION_ENABLED,
    ExecutionFailureCode,
    HarnessError,
    LocalExecutionAttemptRecord,
    LocalExecutionFailure,
    LocalExecutionHarness,
    LocalExecutionRequest,
    LocalExecutionResult,
    real_execution_enabled,
)
from nomos.council.local_adapter import (
    AdapterError,
    AdapterFailureCode,
    DryRunAdapterCandidateProvider,
    DryRunLocalEngineAdapter,
    LocalAdapterFailure,
    LocalEngineAdapter,
    LocalEngineAdapterPolicy,
    LocalEngineDryRunResult,
    LocalEngineExecutionPlan,
    LocalEngineIsolationProfile,
)
from nomos.council.local_provider import (
    DeterministicLocalCandidateProvider,
    LocalCandidateProvider,
    LocalCandidateRequest,
    LocalCandidateResult,
    LocalEngineDescriptor,
    LocalProviderError,
    LocalProviderFailure,
    run_offline_council_with_local_provider,
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

__all__ = [
    "AnswerCandidate", "ArbiterDecision", "BlindReview", "CouncilAuditRecord",
    "CouncilConfidence", "CouncilDisagreementLevel", "CouncilFailureCode",
    "CouncilMode", "CouncilModelError", "CouncilPolicy", "CouncilRiskLevel",
    "CouncilSession", "DisagreementReport", "JudgeScore", "RiskAssessment",
    # MC2 — simulador offline
    "OfflineCouncilInput", "OfflineCouncilResult", "OfflineCouncilSimulator",
    "SimulatedEngineFixture", "SimulatedJudgeFixture", "SimulatedPolicyGateResult",
    "SimulatorError",
    # MC3 — provedor de candidatos local (por contrato)
    "DeterministicLocalCandidateProvider", "LocalCandidateProvider",
    "LocalCandidateRequest", "LocalCandidateResult", "LocalEngineDescriptor",
    "LocalProviderError", "LocalProviderFailure",
    "run_offline_council_with_local_provider",
    # MC4 — adaptador de motor local (dry-run)
    "AdapterError", "AdapterFailureCode", "DryRunAdapterCandidateProvider",
    "DryRunLocalEngineAdapter", "LocalAdapterFailure", "LocalEngineAdapter",
    "LocalEngineAdapterPolicy", "LocalEngineDryRunResult",
    "LocalEngineExecutionPlan", "LocalEngineIsolationProfile",
    # MC5 — harness de execução local FAIL-CLOSED
    "REAL_LOCAL_ENGINE_EXECUTION_ENABLED", "ExecutionFailureCode", "HarnessError",
    "LocalExecutionAttemptRecord", "LocalExecutionFailure", "LocalExecutionHarness",
    "LocalExecutionRequest", "LocalExecutionResult", "real_execution_enabled",
    # MC6 — policy gate (dry-run)
    "CouncilGateDecision", "CouncilGateFailure", "CouncilGateRequest",
    "CouncilGateRisk", "CouncilPolicyGateDryRun", "FinalResponseEnvelope",
    "GateError", "GateFailureCode", "gate_risk_of",
    "run_offline_council_with_policy_gate",
    # MC7 — audit envelope (dry-run, private mode)
    "AuditEnvelopeError", "AuditEnvelopeFailureCode", "CouncilAuditDryRunResult",
    "CouncilAuditEnvelope", "CouncilAuditEnvelopeBuilder",
    "CouncilAuditEnvelopeFailure", "CouncilAuditEventType",
    "CouncilAuditRedactionProfile", "run_offline_council_with_audit_envelope",
]
