"""NOMOS Motor Council — envelope de auditoria em SPEC/DRY-RUN (Fase MC7).

Representa COMO o Conselho registraria eventos no audit log real no futuro, mas
nesta fase é **puramente dry-run**:

    dry_run_only=true
    no_real_audit_write=true
    no_filesystem_write=true
    metadata_only=true
    redacted=true

Nenhum evento é gravado no audit real. Prova que:

    private_mode=true  ⇒  persist_allowed=false

e que os registros são **metadata-only e redigidos**: nunca contêm prompt,
conteúdo de candidato, conteúdo final, engine_id (em modo privado), segredo,
chave ou token — em `to_dict`, `to_json`, `repr` ou `warnings`.

Módulo puro (stdlib + `nomos.council.models`). Sem rede, cloud, SDK remoto, motor,
subprocess, threading, asyncio, FS, env, tempo real ou random. Pureza provada
por teste (AST).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum

from nomos.council.models import CouncilModelError

REDIGIDO = "[REDIGIDO]"

# chaves de metadata que NUNCA podem ser gravadas
_SENSITIVE_KEYS = {
    "prompt", "content", "final_content", "candidate_content", "raw",
    "secret", "token", "api_key", "apikey", "password", "passphrase",
    "credential", "authorization", "bearer", "engine_id", "judge_engine_id",
}
# marcas de valor sensível (checagem por substring, minúsculas)
_SENSITIVE_VALUE_MARKS = ("bearer ", "sk-", "password", "secret", "token",
                          "api_key", "passphrase", "-----begin")


class AuditEnvelopeError(CouncilModelError):
    """Erro de configuração do envelope de auditoria (fail-closed)."""


# --------------------------- enums ---------------------------

class CouncilAuditEventType(str, Enum):
    SESSION_STARTED = "SESSION_STARTED"
    RISK_ASSESSED = "RISK_ASSESSED"
    CANDIDATES_CREATED = "CANDIDATES_CREATED"
    CANDIDATES_ANONYMIZED = "CANDIDATES_ANONYMIZED"
    REVIEWS_CREATED = "REVIEWS_CREATED"
    DISAGREEMENT_REPORTED = "DISAGREEMENT_REPORTED"
    ARBITER_DECIDED = "ARBITER_DECIDED"
    POLICY_GATE_EVALUATED = "POLICY_GATE_EVALUATED"
    FINAL_ENVELOPE_CREATED = "FINAL_ENVELOPE_CREATED"
    PRIVATE_MODE_ENFORCED = "PRIVATE_MODE_ENFORCED"
    AUDIT_DRY_RUN_COMPLETED = "AUDIT_DRY_RUN_COMPLETED"
    AUDIT_DRY_RUN_BLOCKED = "AUDIT_DRY_RUN_BLOCKED"


class AuditEnvelopeFailureCode(str, Enum):
    AUDIT_ENVELOPE_SENSITIVE_METADATA = "AUDIT_ENVELOPE_SENSITIVE_METADATA"
    AUDIT_ENVELOPE_PRIVATE_PERSIST_DENIED = "AUDIT_ENVELOPE_PRIVATE_PERSIST_DENIED"
    AUDIT_ENVELOPE_REAL_WRITE_FORBIDDEN = "AUDIT_ENVELOPE_REAL_WRITE_FORBIDDEN"
    AUDIT_ENVELOPE_NOT_REDACTED = "AUDIT_ENVELOPE_NOT_REDACTED"
    AUDIT_ENVELOPE_INVALID_EVENT = "AUDIT_ENVELOPE_INVALID_EVENT"
    AUDIT_ENVELOPE_DRY_RUN_ONLY = "AUDIT_ENVELOPE_DRY_RUN_ONLY"


@dataclass(frozen=True)
class CouncilAuditEnvelopeFailure:
    code: AuditEnvelopeFailureCode
    reason: str = ""


# --------------------------- redaction helpers ---------------------------

def _has_sensitive(metadata: dict) -> str | None:
    """Devolve motivo se a metadata tiver chave/valor sensível; senão None."""
    for k, v in (metadata or {}).items():
        if str(k).lower() in _SENSITIVE_KEYS:
            return f"chave sensível: {k}"
        if isinstance(v, str) and any(m in v.lower() for m in _SENSITIVE_VALUE_MARKS):
            return "valor sensível em metadata"
        if isinstance(v, dict):
            sub = _has_sensitive(v)
            if sub:
                return sub
    return None


def _safe_metadata(metadata: dict) -> dict:
    """Cópia redigida: chaves sensíveis e valores com marca viram [REDIGIDO]."""
    out: dict = {}
    for k, v in (metadata or {}).items():
        if str(k).lower() in _SENSITIVE_KEYS:
            out[k] = REDIGIDO
        elif isinstance(v, str) and any(m in v.lower() for m in _SENSITIVE_VALUE_MARKS):
            out[k] = REDIGIDO
        elif isinstance(v, dict):
            out[k] = _safe_metadata(v)
        else:
            out[k] = v
    return out


# --------------------------- perfil de redação ---------------------------

@dataclass
class CouncilAuditRedactionProfile:
    metadata_only: bool = True
    redact_content: bool = True
    redact_engine_ids: bool = True
    redact_prompt: bool = True
    redact_scores_detail: bool = False
    allow_counts: bool = True
    allow_failure_codes: bool = True

    def __post_init__(self):
        if self.redact_content is not True:
            raise AuditEnvelopeError("redact_content deve ser true")
        if self.redact_prompt is not True:
            raise AuditEnvelopeError("redact_prompt deve ser true")

    @classmethod
    def for_private(cls) -> "CouncilAuditRedactionProfile":
        """Modo privado ⇒ redação MÁXIMA."""
        return cls(metadata_only=True, redact_content=True, redact_engine_ids=True,
                   redact_prompt=True, redact_scores_detail=True,
                   allow_counts=True, allow_failure_codes=True)

    def to_dict(self) -> dict:
        return {"schema": "nomos.council.audit_redaction_profile.v1",
                "metadata_only": self.metadata_only,
                "redact_content": self.redact_content,
                "redact_engine_ids": self.redact_engine_ids,
                "redact_prompt": self.redact_prompt,
                "redact_scores_detail": self.redact_scores_detail,
                "allow_counts": self.allow_counts,
                "allow_failure_codes": self.allow_failure_codes}


# --------------------------- envelope ---------------------------

@dataclass
class CouncilAuditEnvelope:
    event_type: CouncilAuditEventType
    session_id: str
    private_mode: bool = False
    metadata: dict = field(default_factory=dict, repr=False)
    redacted: bool = True
    persist_allowed: bool = True
    dry_run: bool = True
    would_write_audit: bool = False

    def __post_init__(self):
        if not self.session_id:
            raise AuditEnvelopeError("session_id obrigatório")
        try:
            self.event_type = (self.event_type if isinstance(self.event_type,
                               CouncilAuditEventType)
                               else CouncilAuditEventType(self.event_type))
        except ValueError:
            raise AuditEnvelopeError(
                f"event_type inválido: {self.event_type!r}") from None
        # invariantes inegociáveis desta fase
        self.dry_run = True
        self.would_write_audit = False
        if self.private_mode:
            self.persist_allowed = False

    def has_sensitive_metadata(self) -> str | None:
        return _has_sensitive(self.metadata)

    def to_dict(self) -> dict:
        return {"schema": "nomos.council.audit_envelope.v1",
                "event_type": self.event_type.value, "session_id": self.session_id,
                "dry_run": self.dry_run, "would_write_audit": self.would_write_audit,
                "persist_allowed": self.persist_allowed, "private_mode": self.private_mode,
                "redacted": self.redacted,
                "metadata": _safe_metadata(self.metadata)}   # sempre redigido

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)

    def __repr__(self) -> str:   # nunca vaza metadata sensível
        return (f"CouncilAuditEnvelope(event_type={self.event_type.value}, "
                f"session_id={self.session_id!r}, dry_run={self.dry_run}, "
                f"would_write_audit={self.would_write_audit}, "
                f"persist_allowed={self.persist_allowed}, "
                f"private_mode={self.private_mode}, redacted={self.redacted}, "
                f"metadata_keys={sorted(self.metadata.keys())})")


# --------------------------- resultado dry-run ---------------------------

@dataclass
class CouncilAuditDryRunResult:
    allowed: bool = True
    envelopes: list = field(default_factory=list)
    failure_code: AuditEnvelopeFailureCode | None = None
    warnings: list = field(default_factory=list)
    dry_run: bool = True
    would_write_audit: bool = False

    def __post_init__(self):
        self.dry_run = True
        self.would_write_audit = False

    def to_dict(self) -> dict:
        return {"schema": "nomos.council.audit_dry_run_result.v1",
                "allowed": self.allowed, "dry_run": self.dry_run,
                "would_write_audit": self.would_write_audit,
                "envelopes": [e.to_dict() if hasattr(e, "to_dict") else e
                              for e in self.envelopes],
                "failure_code": self.failure_code.value if self.failure_code else None,
                "warnings": list(self.warnings)}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)


# --------------------------- builder ---------------------------

class CouncilAuditEnvelopeBuilder:
    """Gera envelopes de auditoria dry-run, metadata-only e redigidos.

    Nunca chama audit/vault/policy reais, não grava em disco, não lê env, sem
    tempo/random. Determinístico."""

    def _validar(self, envelopes: list, private_mode: bool
                 ) -> CouncilAuditEnvelopeFailure | None:
        for env in envelopes:
            if getattr(env, "would_write_audit", False):
                return CouncilAuditEnvelopeFailure(
                    AuditEnvelopeFailureCode.AUDIT_ENVELOPE_REAL_WRITE_FORBIDDEN,
                    "envelope tentou escrita real")
            if getattr(env, "redacted", True) is not True:
                return CouncilAuditEnvelopeFailure(
                    AuditEnvelopeFailureCode.AUDIT_ENVELOPE_NOT_REDACTED,
                    "envelope não redigido")
            motivo = env.has_sensitive_metadata()
            if motivo:
                return CouncilAuditEnvelopeFailure(
                    AuditEnvelopeFailureCode.AUDIT_ENVELOPE_SENSITIVE_METADATA, motivo)
            if private_mode and env.persist_allowed:
                return CouncilAuditEnvelopeFailure(
                    AuditEnvelopeFailureCode.AUDIT_ENVELOPE_PRIVATE_PERSIST_DENIED,
                    "modo privado não pode persistir")
        return None

    def validate(self, envelopes: list, private_mode: bool
                 ) -> CouncilAuditDryRunResult:
        falha = self._validar(envelopes, private_mode)
        if falha is not None:
            return CouncilAuditDryRunResult(
                allowed=False, envelopes=envelopes, failure_code=falha.code,
                warnings=[falha.reason])
        return CouncilAuditDryRunResult(allowed=True, envelopes=envelopes)

    def build_for_result(self, result, private_mode: bool,
                         extra_metadata: dict | None = None
                         ) -> CouncilAuditDryRunResult:
        """Monta os envelopes (metadata-only) a partir de um resultado simulado."""
        profile = (CouncilAuditRedactionProfile.for_private() if private_mode
                   else CouncilAuditRedactionProfile())
        session_id = getattr(getattr(result, "session", None), "session_id", "offline-sim")
        n_cand = len(getattr(result, "candidates", []) or [])
        n_rev = len(getattr(result, "reviews", []) or [])
        fc = getattr(result, "failure_code", None)
        fc_val = fc.value if hasattr(fc, "value") else fc

        # metadata SEMPRE metadata-only: só contagens e código de falha
        base_md = {"candidate_count": n_cand, "review_count": n_rev,
                   "failure_code": fc_val, "redaction_profile": profile.to_dict()}
        if extra_metadata:                 # p/ exercitar bloqueio de metadata sensível
            base_md = {**base_md, **extra_metadata}

        eventos = [
            CouncilAuditEventType.SESSION_STARTED,
            CouncilAuditEventType.CANDIDATES_CREATED,
            CouncilAuditEventType.CANDIDATES_ANONYMIZED,
            CouncilAuditEventType.REVIEWS_CREATED,
            CouncilAuditEventType.ARBITER_DECIDED,
            CouncilAuditEventType.POLICY_GATE_EVALUATED,
            CouncilAuditEventType.FINAL_ENVELOPE_CREATED,
        ]
        if private_mode:
            eventos.append(CouncilAuditEventType.PRIVATE_MODE_ENFORCED)
        eventos.append(CouncilAuditEventType.AUDIT_DRY_RUN_COMPLETED)

        envelopes = [CouncilAuditEnvelope(
            event_type=ev, session_id=session_id, private_mode=private_mode,
            metadata=dict(base_md), redacted=True,
            persist_allowed=not private_mode) for ev in eventos]

        return self.validate(envelopes, private_mode)


# --------------------------- integração com o simulador ---------------------------

def run_offline_council_with_audit_envelope(offline_result, *,
                                            private_mode: bool | None = None,
                                            extra_metadata: dict | None = None,
                                            builder: CouncilAuditEnvelopeBuilder | None = None
                                            ) -> CouncilAuditDryRunResult:
    """MC7: recebe o resultado simulado e produz o audit dry-run result.

    Não altera `run()`, não chama audit real, não grava em disco. Em modo privado
    todos os envelopes têm `persist_allowed=false`."""
    if private_mode is None:
        private_mode = bool(getattr(getattr(offline_result, "session", None),
                            "private_mode", False))
    builder = builder or CouncilAuditEnvelopeBuilder()
    return builder.build_for_result(offline_result, private_mode,
                                    extra_metadata=extra_metadata)
