"""NOMOS Motor Council — simulador OFFLINE determinístico (Fase MC2/MC3).

Exercita o pipeline conceitual do Council **sem motor real, sem rede, sem
persistência, sem policy/audit/vault reais**. Tudo é função pura sobre os
modelos puros do MC1 (`nomos.council.models`).

    RiskAssessment → CouncilPolicy → AnswerCandidate → BlindReview(fixtures) →
    DisagreementReport → ArbiterDecision → SimulatedPolicyGateResult →
    CouncilAuditRecord(s)

MC2: candidatos vêm de `SimulatedEngineFixture`.
MC3: `run_with_candidates(...)` aceita candidatos JÁ construídos (ex.: de um
provedor de motores LOCAIS), mantendo juízes/árbitro/gate simulados.

Determinismo: mesma entrada ⇒ mesma saída (sem tempo real, sem random, sem I/O).
Fail-closed: caminhos inseguros/insuficientes viram `failure_code`, nunca crash.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

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
    RiskAssessment,
    _coerce_enum,
)

_ALFABETO = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_FIXTURE_PREFIXO = "fixture:"


class SimulatorError(CouncilModelError):
    """Erro de configuração do simulador (fail-closed)."""


# --------------------------- fixtures ---------------------------

@dataclass
class SimulatedEngineFixture:
    """Resposta JÁ PRONTA (não motor real). engine_id deve começar por 'fixture:'."""
    engine_id: str
    candidate_id: str
    content: str = field(default="", repr=False)
    failure_code: CouncilFailureCode | None = None

    def __post_init__(self):
        if not self.engine_id.startswith(_FIXTURE_PREFIXO):
            raise SimulatorError(f"engine_id deve começar por '{_FIXTURE_PREFIXO}'")
        if not self.candidate_id:
            raise SimulatorError("candidate_id obrigatório")
        if self.failure_code is not None:
            self.failure_code = _coerce_enum(
                CouncilFailureCode, self.failure_code, "failure_code")
        if not self.content and self.failure_code is None:
            raise SimulatorError("content vazio só é permitido com failure_code")

    def __repr__(self) -> str:
        return (f"SimulatedEngineFixture(engine_id={self.engine_id!r}, "
                f"candidate_id={self.candidate_id!r}, content=<{len(self.content)} chars>)")


@dataclass
class SimulatedJudgeFixture:
    """Julgamento JÁ PRONTO. judge_engine_id deve começar por 'fixture:'."""
    judge_engine_id: str
    candidate_alias: str
    overall: int = 0
    score: dict = field(default_factory=dict)
    alerts: list = field(default_factory=list)
    blocked: bool = False

    def __post_init__(self):
        if not self.judge_engine_id.startswith(_FIXTURE_PREFIXO):
            raise SimulatorError(f"judge_engine_id deve começar por '{_FIXTURE_PREFIXO}'")
        if not self.candidate_alias:
            raise SimulatorError("candidate_alias obrigatório")
        if not isinstance(self.overall, int) or isinstance(self.overall, bool):
            raise SimulatorError("overall deve ser inteiro 0–5")
        if not (0 <= self.overall <= 5):
            raise SimulatorError("overall fora de 0–5")

    @property
    def has_critical_alert(self) -> bool:
        return self.blocked or any(
            str(a).lower() in {"critical", "critico", "crítico", "block"}
            for a in self.alerts)


# --------------------------- gate simulado ---------------------------

@dataclass
class SimulatedPolicyGateResult:
    """Resultado de gate SIMULADO (não chama policy real; não executa ação)."""
    allowed: bool = True
    code: str = "ALLOW_SIMULATED"
    reason: str = "simulated only"

    def to_dict(self) -> dict:
        return {"schema": "nomos.council.gate_result.v1", "allowed": self.allowed,
                "code": self.code, "reason": self.reason}


# --------------------------- entrada ---------------------------

@dataclass
class OfflineCouncilInput:
    prompt: str = field(repr=False)
    mode: CouncilMode = CouncilMode.BALANCED
    risk_level: CouncilRiskLevel = CouncilRiskLevel.A1
    private_mode: bool = False
    local_only: bool = True
    contains_sensitive_data: bool = False
    council_enabled: bool = True
    candidate_fixtures: list = field(default_factory=list)
    judge_fixtures: list = field(default_factory=list)
    gate: SimulatedPolicyGateResult | None = None

    def __post_init__(self):
        if not self.prompt:
            raise SimulatorError("prompt obrigatório")
        self.mode = _coerce_enum(CouncilMode, self.mode, "mode")
        self.risk_level = _coerce_enum(CouncilRiskLevel, self.risk_level, "risk_level")
        if self.mode is CouncilMode.PARANOID:
            self.local_only = True

    def __repr__(self) -> str:   # nunca vaza o prompt
        return (f"OfflineCouncilInput(mode={self.mode.value}, "
                f"risk_level={self.risk_level.value}, private_mode={self.private_mode}, "
                f"prompt=<{len(self.prompt)} chars>)")


# --------------------------- resultado ---------------------------

@dataclass
class OfflineCouncilResult:
    session: CouncilSession
    policy: CouncilPolicy
    risk: RiskAssessment
    candidates: list
    anonymized_candidates: list
    reviews: list
    disagreement: DisagreementReport
    arbiter_decision: ArbiterDecision
    policy_gate_result: SimulatedPolicyGateResult
    audit_records: list
    failure_code: CouncilFailureCode | None = None

    def to_dict(self) -> dict:
        return {
            "schema": "nomos.council.offline_result.v1",
            "session": self.session.to_dict(),
            "policy": self.policy.to_dict(),
            "risk": self.risk.to_dict(),
            "candidates": [c.to_dict() for c in self.candidates],
            "anonymized_candidates": [c.to_dict() for c in self.anonymized_candidates],
            "reviews": [r.to_dict() for r in self.reviews],
            "disagreement": self.disagreement.to_dict(),
            "arbiter_decision": self.arbiter_decision.to_dict(),
            "policy_gate_result": self.policy_gate_result.to_dict(),
            "audit_records": [a.to_dict() for a in self.audit_records],
            "failure_code": self.failure_code.value if self.failure_code else None,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)


# --------------------------- simulador ---------------------------

_DISAGREEMENT_HIGH = 3      # spread >= 3 (em 0–5) ⇒ alta
_DISAGREEMENT_MED = 2       # spread >= 2 ⇒ média


class OfflineCouncilSimulator:
    """Pipeline puro e determinístico. Nada de disco/rede/motor."""

    def run(self, entrada: OfflineCouncilInput) -> OfflineCouncilResult:
        candidates: list[AnswerCandidate] = []
        alias_por_candidato: dict[str, str] = {}
        engine_por_alias: dict[str, str] = {}
        for i, fx in enumerate(entrada.candidate_fixtures):
            alias = _ALFABETO[i] if i < len(_ALFABETO) else f"C{i}"
            candidates.append(AnswerCandidate(
                candidate_id=fx.candidate_id, engine_id=fx.engine_id,
                content=fx.content, failure_code=fx.failure_code))
            alias_por_candidato[fx.candidate_id] = alias
            engine_por_alias[alias] = fx.engine_id
        return self.run_with_candidates(
            mode=entrada.mode, risk_level=entrada.risk_level,
            local_only=entrada.local_only, private_mode=entrada.private_mode,
            contains_sensitive_data=entrada.contains_sensitive_data,
            council_enabled=entrada.council_enabled, candidates=candidates,
            alias_por_candidato=alias_por_candidato, engine_por_alias=engine_por_alias,
            judge_fixtures=entrada.judge_fixtures, gate=entrada.gate)

    def run_with_candidates(self, *, candidates, alias_por_candidato, engine_por_alias,
                            judge_fixtures, mode=CouncilMode.BALANCED,
                            risk_level=CouncilRiskLevel.A1, local_only=True,
                            private_mode=False, contains_sensitive_data=False,
                            council_enabled=True, gate=None,
                            provider_failure=None) -> OfflineCouncilResult:
        """Núcleo do pipeline sobre candidatos JÁ construídos (AnswerCandidate).

        Reutilizado pela integração de motores LOCAIS (MC3): só os candidatos
        mudam de origem; juízes, árbitro e gate continuam simulados."""
        mode = _coerce_enum(CouncilMode, mode, "mode")
        risk_level = _coerce_enum(CouncilRiskLevel, risk_level, "risk_level")
        if mode is CouncilMode.PARANOID:
            local_only = True

        risk = RiskAssessment(risk_level=risk_level,
                              contains_sensitive_data=contains_sensitive_data)
        policy = CouncilPolicy(mode=mode, local_only=local_only,
                               persist_candidates=not private_mode,
                               persist_reviews=not private_mode)
        if private_mode:
            policy.persist_candidates = False
            policy.persist_reviews = False

        elegiveis = [c for c in candidates if c.failure_code is None and c.content]
        anon = [c.anonymized(alias=alias_por_candidato[c.candidate_id])
                for c in elegiveis]
        session = CouncilSession(
            session_id="offline-sim", mode=mode, risk_level=risk_level,
            local_only=local_only, private_mode=private_mode,
            candidate_count=len(candidates), judge_count=len(judge_fixtures))
        gate = gate or SimulatedPolicyGateResult()

        def _bloqueado(fc, motivo, reviews=None, disagreement=None):
            decisao = ArbiterDecision(
                decision_id="dec-offline", blocked=True, final_content="",
                confidence=CouncilConfidence.LOW, requires_policy_gate=True,
                reasons=[motivo])
            return self._montar(session, policy, risk, candidates, anon,
                                reviews or [], disagreement or DisagreementReport(),
                                decisao, gate, private_mode, fc)

        if not council_enabled:
            return _bloqueado(CouncilFailureCode.COUNCIL_DISABLED, "conselho desligado")
        if not elegiveis:
            falhou = next((c.failure_code for c in candidates
                           if c.failure_code is not None), None)
            fc = provider_failure or falhou or CouncilFailureCode.NO_ELIGIBLE_LOCAL_ENGINE
            return _bloqueado(fc, "sem candidato elegível")

        reviews: list[BlindReview] = []
        for j, jf in enumerate(judge_fixtures):
            reviews.append(BlindReview(
                review_id=f"rev-{j}", judge_engine_id=jf.judge_engine_id,
                candidate_alias=jf.candidate_alias,
                candidate_engine_id=engine_por_alias.get(jf.candidate_alias),
                score={"overall": jf.overall}, alerts=list(jf.alerts),
                blocked=jf.blocked))

        nao_conflito = [r for r in reviews if not r.is_self_judging]
        efetivas = nao_conflito if nao_conflito else reviews
        # todos os juízes são autores (sem juiz limpo) ⇒ fail-closed
        if judge_fixtures and not nao_conflito:
            return _bloqueado(CouncilFailureCode.INSUFFICIENT_JUDGES,
                              "todos os juízes são autores (conflito)", reviews)

        if any(jf.has_critical_alert for jf in judge_fixtures):
            return _bloqueado(CouncilFailureCode.ARBITER_UNSAFE_OUTPUT,
                              "alerta crítico de juiz", efetivas)

        overalls = [jf.overall for jf in judge_fixtures]
        spread = (max(overalls) - min(overalls)) if overalls else 0
        nivel = (CouncilDisagreementLevel.HIGH if spread >= _DISAGREEMENT_HIGH
                 else CouncilDisagreementLevel.MEDIUM if spread >= _DISAGREEMENT_MED
                 else CouncilDisagreementLevel.LOW)
        disagreement = DisagreementReport(level=nivel, score_spread=float(spread))
        if nivel is CouncilDisagreementLevel.HIGH:
            return _bloqueado(CouncilFailureCode.JUDGE_DISAGREEMENT_HIGH,
                              "divergência alta entre juízes", efetivas, disagreement)

        if gate.allowed is False:
            return _bloqueado(CouncilFailureCode.POLICY_GATE_DENIED,
                              f"gate negou: {gate.reason}", efetivas, disagreement)

        melhor_alias = self._melhor_alias(judge_fixtures, anon)
        confianca = (CouncilConfidence.HIGH if nivel is CouncilDisagreementLevel.LOW
                     else CouncilConfidence.MEDIUM)
        decisao = ArbiterDecision(
            decision_id="dec-offline", selected_candidate_alias=melhor_alias,
            final_content=f"[simulado] resposta do candidato {melhor_alias}",
            confidence=confianca, requires_policy_gate=True, blocked=False)
        return self._montar(session, policy, risk, candidates, anon, efetivas,
                            disagreement, decisao, gate, private_mode, None)

    @staticmethod
    def _melhor_alias(judge_fixtures, anon) -> str | None:
        if not anon:
            return None
        soma: dict[str, int] = {}
        for jf in judge_fixtures:
            soma[jf.candidate_alias] = soma.get(jf.candidate_alias, 0) + jf.overall
        if soma:
            return sorted(soma.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        return anon[0].candidate_id

    @staticmethod
    def _montar(session, policy, risk, candidates, anon, reviews, disagreement,
                decisao, gate, private_mode, failure_code) -> OfflineCouncilResult:
        audit = [CouncilAuditRecord(
            session_id=session.session_id, event_type="council.offline.simulated",
            redacted=True, private_mode=private_mode,
            metadata={"mode": session.mode.value,
                      "failure_code": failure_code.value if failure_code else None})]
        return OfflineCouncilResult(
            session=session, policy=policy, risk=risk, candidates=candidates,
            anonymized_candidates=anon, reviews=reviews, disagreement=disagreement,
            arbiter_decision=decisao, policy_gate_result=gate, audit_records=audit,
            failure_code=failure_code)
