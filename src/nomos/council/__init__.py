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
]
