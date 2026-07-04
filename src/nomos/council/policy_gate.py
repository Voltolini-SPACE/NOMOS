"""NOMOS Motor Council — integração com o Policy Gate em SPEC/DRY-RUN (Fase MC6).

Representa COMO a resposta final do Conselho passará pelo Policy Gate A0–A6 real
no futuro — mas nesta fase é **puramente dry-run**:

    dry_run_only=true
    no_side_effects=true
    no_real_approval=true
    no_real_policy_mutation=true

Toda resposta final simulada só é considerada liberada se o gate dry-run devolver
`allowed=true`. Nenhuma policy real, aprovação real, motor, rede, cloud, FS, env,
tempo ou random é acionada. Decisões são determinísticas.

Módulo puro (stdlib + modelos do council). Pureza provada por teste (AST).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum

from nomos.council.models import (
    CouncilMode,
    CouncilModelError,
    CouncilRiskLevel,
    _coerce_enum,
)


class GateError(CouncilModelError):
    """Erro de configuração do gate dry-run (fail-closed)."""


# --------------------------- risco / falhas ---------------------------

class CouncilGateRisk(str, Enum):
    LOW = "low"            # A0, A1
    MEDIUM = "medium"      # A2
    HIGH = "high"          # A3, A4, A5
    DESTRUCTIVE = "destructive"  # A6


def gate_risk_of(risk_level: CouncilRiskLevel) -> CouncilGateRisk:
    v = risk_level.value if isinstance(risk_level, CouncilRiskLevel) else str(risk_level)
    if v in ("A0", "A1"):
        return CouncilGateRisk.LOW
    if v == "A2":
        return CouncilGateRisk.MEDIUM
    if v == "A6":
        return CouncilGateRisk.DESTRUCTIVE
    return CouncilGateRisk.HIGH   # A3, A4, A5


class GateFailureCode(str, Enum):
    GATE_ARBITER_BLOCKED = "GATE_ARBITER_BLOCKED"
    GATE_EMPTY_FINAL_CONTENT = "GATE_EMPTY_FINAL_CONTENT"
    GATE_A6_DENIED = "GATE_A6_DENIED"
    GATE_REQUIRES_APPROVAL = "GATE_REQUIRES_APPROVAL"
    GATE_SENSITIVE_DATA_REQUIRES_STRICT_MODE = "GATE_SENSITIVE_DATA_REQUIRES_STRICT_MODE"
    GATE_HIGH_RISK_DRY_RUN_ONLY = "GATE_HIGH_RISK_DRY_RUN_ONLY"
    GATE_POLICY_UNAVAILABLE = "GATE_POLICY_UNAVAILABLE"
    GATE_DRY_RUN_ONLY = "GATE_DRY_RUN_ONLY"


@dataclass(frozen=True)
class CouncilGateFailure:
    code: GateFailureCode
    reason: str = ""


# --------------------------- pedido ---------------------------

@dataclass
class CouncilGateRequest:
    session_id: str
    risk_level: CouncilRiskLevel
    mode: CouncilMode = CouncilMode.BALANCED
    private_mode: bool = False
    contains_sensitive_data: bool = False
    requires_human_approval: bool = False
    arbiter_blocked: bool = False
    final_content_chars: int = 0
    has_final_content: bool = True

    def __post_init__(self):
        if not self.session_id:
            raise GateError("session_id obrigatório")
        self.risk_level = _coerce_enum(CouncilRiskLevel, self.risk_level, "risk_level")
        self.mode = _coerce_enum(CouncilMode, self.mode, "mode")
        if not isinstance(self.final_content_chars, int) or self.final_content_chars < 0:
            raise GateError("final_content_chars deve ser inteiro >= 0")

    def to_dict(self) -> dict:
        return {"schema": "nomos.council.gate_request.v1",
                "session_id": self.session_id, "mode": self.mode.value,
                "risk_level": self.risk_level.value, "private_mode": self.private_mode,
                "contains_sensitive_data": self.contains_sensitive_data,
                "requires_human_approval": self.requires_human_approval,
                "arbiter_blocked": self.arbiter_blocked,
                "final_content_chars": self.final_content_chars,
                "has_final_content": self.has_final_content}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)

    def __repr__(self) -> str:   # não há conteúdo aqui; só metadados
        return (f"CouncilGateRequest(session_id={self.session_id!r}, "
                f"mode={self.mode.value}, risk_level={self.risk_level.value}, "
                f"final_content_chars={self.final_content_chars}, "
                f"has_final_content={self.has_final_content})")


# --------------------------- decisão ---------------------------

@dataclass
class CouncilGateDecision:
    allowed: bool
    failure_code: GateFailureCode | None = None
    requires_human_approval: bool = False
    reasons: list = field(default_factory=list)
    dry_run: bool = True
    would_call_real_policy: bool = False
    would_request_approval: bool = False

    def __post_init__(self):
        # invariantes inegociáveis desta fase
        self.dry_run = True
        self.would_call_real_policy = False
        self.would_request_approval = False

    def to_dict(self) -> dict:
        return {"schema": "nomos.council.gate_decision.v1", "dry_run": self.dry_run,
                "allowed": self.allowed,
                "failure_code": self.failure_code.value if self.failure_code else None,
                "requires_human_approval": self.requires_human_approval,
                "would_call_real_policy": self.would_call_real_policy,
                "would_request_approval": self.would_request_approval,
                "reasons": list(self.reasons)}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)


# --------------------------- envelope final ---------------------------

@dataclass
class FinalResponseEnvelope:
    session_id: str
    gate_decision: dict
    allowed: bool = False
    blocked: bool = True
    content: str | None = field(default=None, repr=False)
    content_redacted: bool = True
    persist_allowed: bool = True

    def __post_init__(self):
        # gate negou ⇒ nunca há conteúdo
        if not self.allowed:
            self.blocked = True
            self.content = None
        else:
            self.blocked = False

    def to_dict(self) -> dict:
        return {"schema": "nomos.council.final_response.v1",
                "session_id": self.session_id, "allowed": self.allowed,
                "blocked": self.blocked, "content": None,   # nunca serializa o conteúdo
                "content_redacted": self.content_redacted,
                "persist_allowed": self.persist_allowed,
                "gate_decision": self.gate_decision}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)

    def __repr__(self) -> str:   # conteúdo nunca aparece
        n = len(self.content) if self.content else 0
        return (f"FinalResponseEnvelope(session_id={self.session_id!r}, "
                f"allowed={self.allowed}, blocked={self.blocked}, "
                f"content=<{n} chars, redacted={self.content_redacted}>, "
                f"persist_allowed={self.persist_allowed})")


# --------------------------- gate dry-run ---------------------------

class CouncilPolicyGateDryRun:
    """Gate SIMULADO A0–A6. Determinístico, fail-closed, sem efeitos reais.

    Nunca chama policy/approval/vault/audit reais; sem motor/rede/cloud/FS/env/
    tempo/random."""

    def _deny(self, code: GateFailureCode, req: CouncilGateRequest) -> CouncilGateDecision:
        return CouncilGateDecision(
            allowed=False, failure_code=code,
            requires_human_approval=req.requires_human_approval,
            reasons=[code.value])

    def evaluate(self, request: CouncilGateRequest) -> CouncilGateDecision:
        rl = request.risk_level
        # ordem determinística das regras (7.1 → 7.7)
        if request.arbiter_blocked:
            return self._deny(GateFailureCode.GATE_ARBITER_BLOCKED, request)
        if not request.has_final_content:
            return self._deny(GateFailureCode.GATE_EMPTY_FINAL_CONTENT, request)
        if rl is CouncilRiskLevel.A6:
            return self._deny(GateFailureCode.GATE_A6_DENIED, request)
        if request.requires_human_approval:
            # MC6 é dry-run: NÃO chama aprovação real ⇒ bloqueia
            return self._deny(GateFailureCode.GATE_REQUIRES_APPROVAL, request)
        if request.contains_sensitive_data:
            return self._deny(
                GateFailureCode.GATE_SENSITIVE_DATA_REQUIRES_STRICT_MODE, request)
        if gate_risk_of(rl) is CouncilGateRisk.HIGH:   # A3, A4, A5
            return self._deny(GateFailureCode.GATE_HIGH_RISK_DRY_RUN_ONLY, request)
        # A0, A1, A2 (baixo/médio), sem bloqueios acima ⇒ liberado
        return CouncilGateDecision(allowed=True, failure_code=None,
                                   requires_human_approval=False, reasons=[])


# --------------------------- integração com o simulador ---------------------------

def run_offline_council_with_policy_gate(offline_result, *,
                                         requires_human_approval: bool = False,
                                         contains_sensitive_data: bool | None = None,
                                         gate: CouncilPolicyGateDryRun | None = None
                                         ) -> FinalResponseEnvelope:
    """MC6: passa a resposta final SIMULADA pelo gate dry-run e devolve o envelope.

    Não altera o `run()` existente; não chama policy/approval reais. Se o gate
    negar, o envelope não contém conteúdo. Em modo privado, `persist_allowed=false`."""
    sess = offline_result.session
    arb = offline_result.arbiter_decision
    sensivel = (offline_result.risk.contains_sensitive_data
                if contains_sensitive_data is None else contains_sensitive_data)

    req = CouncilGateRequest(
        session_id=sess.session_id, mode=sess.mode, risk_level=sess.risk_level,
        private_mode=sess.private_mode, contains_sensitive_data=sensivel,
        requires_human_approval=requires_human_approval,
        arbiter_blocked=arb.blocked,
        final_content_chars=len(arb.final_content or ""),
        has_final_content=bool(arb.final_content) and not arb.blocked)

    gate = gate or CouncilPolicyGateDryRun()
    decisao = gate.evaluate(req)
    conteudo = arb.final_content if decisao.allowed else None
    return FinalResponseEnvelope(
        session_id=sess.session_id, gate_decision=decisao.to_dict(),
        allowed=decisao.allowed, blocked=not decisao.allowed, content=conteudo,
        persist_allowed=not sess.private_mode)
