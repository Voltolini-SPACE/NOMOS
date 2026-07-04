"""NOMOS Motor Council — modelos de dados puros (Fase MC1).

stdlib-only. Sem I/O, sem rede, sem motor/LLM, sem persistência. As invariantes
de segurança são impostas por construção (fail-closed) em `__post_init__`:

- local_only  ⇒ cloud_allowed = False
- paranoid    ⇒ local_only = True e cloud_allowed = False
- private_mode ⇒ persist_allowed = False
- contains_sensitive_data ⇒ cloud negada (cloud_denied_reason preenchido)

Serialização: to_dict / from_dict / to_json / from_json, determinística. `repr`
de modelos que podem conter texto do usuário NÃO imprime o conteúdo (redação).
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from enum import Enum


class CouncilModelError(ValueError):
    """Erro de validação de um modelo do Council (fail-closed)."""


# --------------------------- enums ---------------------------

class CouncilMode(str, Enum):
    FAST = "fast"
    BALANCED = "balanced"
    CRITICAL = "critical"
    PARANOID = "paranoid"


class CouncilRiskLevel(str, Enum):
    A0 = "A0"
    A1 = "A1"
    A2 = "A2"
    A3 = "A3"
    A4 = "A4"
    A5 = "A5"
    A6 = "A6"


class CouncilConfidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CouncilDisagreementLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CouncilFailureCode(str, Enum):
    COUNCIL_DISABLED = "COUNCIL_DISABLED"
    NO_ELIGIBLE_LOCAL_ENGINE = "NO_ELIGIBLE_LOCAL_ENGINE"
    CLOUD_BLOCKED_BY_LOCAL_LOCK = "CLOUD_BLOCKED_BY_LOCAL_LOCK"
    SENSITIVE_DATA_CLOUD_DENIED = "SENSITIVE_DATA_CLOUD_DENIED"
    JUDGE_DISAGREEMENT_HIGH = "JUDGE_DISAGREEMENT_HIGH"
    ARBITER_UNSAFE_OUTPUT = "ARBITER_UNSAFE_OUTPUT"
    POLICY_GATE_DENIED = "POLICY_GATE_DENIED"
    PRIVATE_MODE_NO_PERSIST = "PRIVATE_MODE_NO_PERSIST"
    INSUFFICIENT_JUDGES = "INSUFFICIENT_JUDGES"
    ENGINE_TIMEOUT = "ENGINE_TIMEOUT"
    ENGINE_FAILED = "ENGINE_FAILED"


def _coerce_enum(cls, valor, campo: str):
    if isinstance(valor, cls):
        return valor
    try:
        return cls(valor)
    except ValueError:
        validos = ", ".join(e.value for e in cls)
        raise CouncilModelError(
            f"{campo} inválido: {valor!r} (use um de: {validos})") from None


def _ser(v):
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, dict):
        return {k: _ser(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_ser(x) for x in v]
    return v


# --------------------------- base ---------------------------

class _Model:
    """Mixin de serialização determinística. Cada modelo define SCHEMA."""

    SCHEMA: str = ""

    def to_dict(self) -> dict:
        from dataclasses import asdict
        d = {"schema": self.SCHEMA}
        d.update({k: _ser(v) for k, v in asdict(self).items()})
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)

    @classmethod
    def _check_schema(cls, data: dict) -> dict:
        if not isinstance(data, dict):
            raise CouncilModelError("payload deve ser um objeto JSON")
        sc = data.get("schema")
        if sc is not None and sc != cls.SCHEMA:
            raise CouncilModelError(
                f"schema inválido: esperado {cls.SCHEMA!r}, veio {sc!r}")
        return {k: v for k, v in data.items() if k != "schema"}

    @classmethod
    def from_json(cls, texto: str):
        try:
            data = json.loads(texto)
        except json.JSONDecodeError as exc:
            raise CouncilModelError(f"JSON inválido: {exc}") from None
        return cls.from_dict(data)


def _novo_id(prefixo: str) -> str:
    return f"{prefixo}_{uuid.uuid4().hex[:12]}"


# --------------------------- session ---------------------------

@dataclass
class CouncilSession(_Model):
    SCHEMA = "nomos.council.session.v1"
    session_id: str
    mode: CouncilMode
    risk_level: CouncilRiskLevel
    local_only: bool = True
    private_mode: bool = False
    cloud_allowed: bool = False
    candidate_count: int = 0
    judge_count: int = 0

    def __post_init__(self):
        if not self.session_id:
            raise CouncilModelError("session_id obrigatório")
        self.mode = _coerce_enum(CouncilMode, self.mode, "mode")
        self.risk_level = _coerce_enum(CouncilRiskLevel, self.risk_level, "risk_level")
        if self.candidate_count < 0 or self.judge_count < 0:
            raise CouncilModelError("candidate_count/judge_count não podem ser negativos")
        # invariantes de segurança (fail-closed, por construção)
        if self.mode is CouncilMode.PARANOID:
            self.local_only = True
        if self.local_only:
            self.cloud_allowed = False

    @property
    def persist_allowed(self) -> bool:
        """Modo privado nunca permite persistência."""
        return not self.private_mode

    @classmethod
    def from_dict(cls, data: dict) -> "CouncilSession":
        d = cls._check_schema(data)
        return cls(
            session_id=d.get("session_id", ""),
            mode=d.get("mode", CouncilMode.BALANCED),
            risk_level=d.get("risk_level", CouncilRiskLevel.A0),
            local_only=bool(d.get("local_only", True)),
            private_mode=bool(d.get("private_mode", False)),
            cloud_allowed=bool(d.get("cloud_allowed", False)),
            candidate_count=int(d.get("candidate_count", 0)),
            judge_count=int(d.get("judge_count", 0)),
        )


# --------------------------- policy ---------------------------

@dataclass
class CouncilPolicy(_Model):
    SCHEMA = "nomos.council.policy.v1"
    mode: CouncilMode
    max_risk: CouncilRiskLevel = CouncilRiskLevel.A3
    local_only: bool = True
    cloud_allowed: bool = False
    persist_candidates: bool = False
    persist_reviews: bool = False
    require_final_policy_gate: bool = True
    allow_sensitive_data_to_cloud: bool = False

    def __post_init__(self):
        self.mode = _coerce_enum(CouncilMode, self.mode, "mode")
        self.max_risk = _coerce_enum(CouncilRiskLevel, self.max_risk, "max_risk")
        if self.mode is CouncilMode.PARANOID:
            self.local_only = True
            self.persist_candidates = False
            self.persist_reviews = False
        if self.local_only:
            self.cloud_allowed = False
            self.allow_sensitive_data_to_cloud = False

    @classmethod
    def from_dict(cls, data: dict) -> "CouncilPolicy":
        d = cls._check_schema(data)
        return cls(
            mode=d.get("mode", CouncilMode.BALANCED),
            max_risk=d.get("max_risk", CouncilRiskLevel.A3),
            local_only=bool(d.get("local_only", True)),
            cloud_allowed=bool(d.get("cloud_allowed", False)),
            persist_candidates=bool(d.get("persist_candidates", False)),
            persist_reviews=bool(d.get("persist_reviews", False)),
            require_final_policy_gate=bool(d.get("require_final_policy_gate", True)),
            allow_sensitive_data_to_cloud=bool(d.get("allow_sensitive_data_to_cloud", False)),
        )


# --------------------------- risk ---------------------------

@dataclass
class RiskAssessment(_Model):
    SCHEMA = "nomos.council.risk.v1"
    risk_level: CouncilRiskLevel
    contains_sensitive_data: bool = False
    requires_human_approval: bool = False
    cloud_denied_reason: str | None = None
    reasons: list = field(default_factory=list)

    def __post_init__(self):
        self.risk_level = _coerce_enum(CouncilRiskLevel, self.risk_level, "risk_level")
        if not isinstance(self.reasons, list) or any(
                not isinstance(r, str) for r in self.reasons):
            raise CouncilModelError("reasons deve ser lista de strings")
        # dado sensível ⇒ cloud negada por representação
        if self.contains_sensitive_data and not self.cloud_denied_reason:
            self.cloud_denied_reason = "contains_sensitive_data"

    @property
    def cloud_allowed(self) -> bool:
        return not self.contains_sensitive_data and self.cloud_denied_reason is None

    @classmethod
    def from_dict(cls, data: dict) -> "RiskAssessment":
        d = cls._check_schema(data)
        return cls(
            risk_level=d.get("risk_level", CouncilRiskLevel.A0),
            contains_sensitive_data=bool(d.get("contains_sensitive_data", False)),
            requires_human_approval=bool(d.get("requires_human_approval", False)),
            cloud_denied_reason=d.get("cloud_denied_reason"),
            reasons=list(d.get("reasons", [])),
        )


# --------------------------- candidate ---------------------------

@dataclass
class AnswerCandidate(_Model):
    SCHEMA = "nomos.council.candidate.v1"
    candidate_id: str
    engine_id: str
    content: str = field(default="", repr=False)      # nunca no repr (redação)
    redacted: bool = False
    metadata: dict = field(default_factory=dict, repr=False)
    failure_code: CouncilFailureCode | None = None

    def __post_init__(self):
        if not self.candidate_id:
            raise CouncilModelError("candidate_id obrigatório")
        if not self.engine_id:
            raise CouncilModelError("engine_id obrigatório")
        if self.failure_code is not None:
            self.failure_code = _coerce_enum(
                CouncilFailureCode, self.failure_code, "failure_code")
        if not self.content and self.failure_code is None:
            raise CouncilModelError(
                "content vazio só é permitido quando há failure_code")

    def __repr__(self) -> str:  # não vaza conteúdo do usuário
        return (f"AnswerCandidate(candidate_id={self.candidate_id!r}, "
                f"engine_id={self.engine_id!r}, content=<{len(self.content)} chars, "
                f"redacted={self.redacted}>)")

    def anonymized(self, alias: str | None = None) -> "AnswerCandidate":
        """Versão para o juiz: SEM autoria (engine_id neutralizado)."""
        return AnswerCandidate(
            candidate_id=alias or self.candidate_id,
            engine_id="ANON",
            content=self.content,
            redacted=self.redacted,
            metadata={},
            failure_code=self.failure_code,
        )

    @classmethod
    def from_dict(cls, data: dict) -> "AnswerCandidate":
        d = cls._check_schema(data)
        return cls(
            candidate_id=d.get("candidate_id", ""),
            engine_id=d.get("engine_id", ""),
            content=d.get("content", ""),
            redacted=bool(d.get("redacted", False)),
            metadata=dict(d.get("metadata", {})),
            failure_code=d.get("failure_code"),
        )


# --------------------------- blind review ---------------------------

@dataclass
class BlindReview(_Model):
    SCHEMA = "nomos.council.review.v1"
    review_id: str
    judge_engine_id: str
    candidate_alias: str
    candidate_engine_id: str | None = None    # p/ detectar autojulgamento; nunca vai ao juiz
    score: dict = field(default_factory=dict)
    alerts: list = field(default_factory=list)
    blocked: bool = False

    def __post_init__(self):
        if not self.review_id:
            raise CouncilModelError("review_id obrigatório")
        if not self.candidate_alias:
            raise CouncilModelError("candidate_alias obrigatório")

    @property
    def is_self_judging(self) -> bool:
        """True se o juiz é o autor do candidato (quando a autoria é conhecida)."""
        return (self.candidate_engine_id is not None
                and self.judge_engine_id == self.candidate_engine_id)

    def redacted_public(self) -> dict:
        """Forma anônima entregue ao juiz: SEM judge_engine_id nem autoria."""
        return {
            "schema": self.SCHEMA,
            "review_id": self.review_id,
            "candidate_alias": self.candidate_alias,
            "score": _ser(self.score),
            "alerts": list(self.alerts),
            "blocked": self.blocked,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BlindReview":
        d = cls._check_schema(data)
        return cls(
            review_id=d.get("review_id", ""),
            judge_engine_id=d.get("judge_engine_id", ""),
            candidate_alias=d.get("candidate_alias", ""),
            candidate_engine_id=d.get("candidate_engine_id"),
            score=dict(d.get("score", {})),
            alerts=list(d.get("alerts", [])),
            blocked=bool(d.get("blocked", False)),
        )


# --------------------------- judge score ---------------------------

_CRITERIOS = ("correctness", "clarity", "safety", "privacy", "usefulness",
              "evidence", "hallucination_risk")


@dataclass
class JudgeScore(_Model):
    SCHEMA = "nomos.council.judge_score.v1"
    candidate_alias: str
    correctness: int
    clarity: int
    safety: int
    privacy: int
    usefulness: int
    evidence: int
    hallucination_risk: int
    followed_local_first: bool = True
    requires_human_approval: bool = False
    contains_sensitive_data: bool = False

    def __post_init__(self):
        if not self.candidate_alias:
            raise CouncilModelError("candidate_alias obrigatório")
        for c in _CRITERIOS:
            v = getattr(self, c)
            if not isinstance(v, int) or isinstance(v, bool):
                raise CouncilModelError(f"{c} deve ser inteiro 0–5")
            if not (0 <= v <= 5):
                raise CouncilModelError(f"{c} fora do intervalo 0–5: {v}")

    @classmethod
    def from_dict(cls, data: dict) -> "JudgeScore":
        d = cls._check_schema(data)
        return cls(
            candidate_alias=d.get("candidate_alias", ""),
            correctness=d.get("correctness", 0),
            clarity=d.get("clarity", 0),
            safety=d.get("safety", 0),
            privacy=d.get("privacy", 0),
            usefulness=d.get("usefulness", 0),
            evidence=d.get("evidence", 0),
            hallucination_risk=d.get("hallucination_risk", 0),
            followed_local_first=bool(d.get("followed_local_first", True)),
            requires_human_approval=bool(d.get("requires_human_approval", False)),
            contains_sensitive_data=bool(d.get("contains_sensitive_data", False)),
        )


# --------------------------- arbiter ---------------------------

@dataclass
class ArbiterDecision(_Model):
    SCHEMA = "nomos.council.arbiter.v1"
    decision_id: str
    selected_candidate_alias: str | None = None
    final_content: str = field(default="", repr=False)
    confidence: CouncilConfidence = CouncilConfidence.MEDIUM
    requires_policy_gate: bool = True
    blocked: bool = False
    reasons: list = field(default_factory=list)

    def __post_init__(self):
        if not self.decision_id:
            raise CouncilModelError("decision_id obrigatório")
        self.confidence = _coerce_enum(CouncilConfidence, self.confidence, "confidence")
        if not self.blocked and not self.final_content:
            raise CouncilModelError(
                "final_content vazio só é permitido quando blocked=True")

    def __repr__(self) -> str:
        return (f"ArbiterDecision(decision_id={self.decision_id!r}, "
                f"confidence={self.confidence.value}, blocked={self.blocked}, "
                f"final_content=<{len(self.final_content)} chars>)")

    @classmethod
    def from_dict(cls, data: dict) -> "ArbiterDecision":
        d = cls._check_schema(data)
        return cls(
            decision_id=d.get("decision_id", ""),
            selected_candidate_alias=d.get("selected_candidate_alias"),
            final_content=d.get("final_content", ""),
            confidence=d.get("confidence", CouncilConfidence.MEDIUM),
            requires_policy_gate=bool(d.get("requires_policy_gate", True)),
            blocked=bool(d.get("blocked", False)),
            reasons=list(d.get("reasons", [])),
        )


# --------------------------- disagreement ---------------------------

@dataclass
class DisagreementReport(_Model):
    SCHEMA = "nomos.council.disagreement.v1"
    level: CouncilDisagreementLevel = CouncilDisagreementLevel.LOW
    score_spread: float = 0.0
    requires_clarification: bool = False
    reasons: list = field(default_factory=list)

    def __post_init__(self):
        self.level = _coerce_enum(CouncilDisagreementLevel, self.level, "level")
        self.score_spread = float(self.score_spread)
        if self.level is CouncilDisagreementLevel.HIGH:
            self.requires_clarification = True   # nunca finge certeza

    @classmethod
    def from_dict(cls, data: dict) -> "DisagreementReport":
        d = cls._check_schema(data)
        return cls(
            level=d.get("level", CouncilDisagreementLevel.LOW),
            score_spread=float(d.get("score_spread", 0.0)),
            requires_clarification=bool(d.get("requires_clarification", False)),
            reasons=list(d.get("reasons", [])),
        )


# --------------------------- audit record ---------------------------

@dataclass
class CouncilAuditRecord(_Model):
    SCHEMA = "nomos.council.audit.v1"
    session_id: str
    event_type: str
    redacted: bool = True
    private_mode: bool = False
    metadata: dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        if not self.session_id:
            raise CouncilModelError("session_id obrigatório")
        if not self.event_type:
            raise CouncilModelError("event_type obrigatório")

    @property
    def persist_allowed(self) -> bool:
        return not self.private_mode

    def __repr__(self) -> str:   # não imprime metadata (pode conter texto)
        return (f"CouncilAuditRecord(session_id={self.session_id!r}, "
                f"event_type={self.event_type!r}, redacted={self.redacted}, "
                f"private_mode={self.private_mode}, "
                f"metadata=<{len(self.metadata)} keys>)")

    @classmethod
    def from_dict(cls, data: dict) -> "CouncilAuditRecord":
        d = cls._check_schema(data)
        return cls(
            session_id=d.get("session_id", ""),
            event_type=d.get("event_type", ""),
            redacted=bool(d.get("redacted", True)),
            private_mode=bool(d.get("private_mode", False)),
            metadata=dict(d.get("metadata", {})),
        )


# helper público p/ fases futuras (não executa nada)
def novo_session_id() -> str:
    return _novo_id("sess")
