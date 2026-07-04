"""NOMOS Motor Council — harness de execução local FAIL-CLOSED (Fase MC5).

Aqui vive o CONTRATO de uma execução de motor local real futura — mas ela é
**impossível de acionar nesta fase**. A trava é uma constante literal:

    REAL_LOCAL_ENGINE_EXECUTION_ENABLED = False

Qualquer tentativa de execução real falha fechado (`REAL_EXECUTION_DISABLED`),
com `executed=false` e `candidate=null` SEMPRE. Não há função pública que ligue a
trava, ela não vem de variáveis de ambiente, de config nem de argumento, e o
módulo não lê nenhuma variável do sistema. Remover a trava exigiria uma edição
explícita e auditável deste arquivo.

O dry-run do MC4 continua funcionando (esta fase não o quebra).

Módulo puro (stdlib + modelos do council). Sem rede, cloud, SDK remoto, motor
real, subprocess, threading, asyncio, FS, env, tempo real ou random. Pureza
provada por teste (AST).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum

from nomos.council.models import (
    CouncilMode,
    CouncilModelError,
    CouncilRiskLevel,
    _coerce_enum,
)

# --------------------------------------------------------------------------
# TRAVA INEGOCIÁVEL DESTA FASE: execução real de motor local DESLIGADA.
# Literal `False`. Não vem de env/config/argumento. Sem API para ativar.
# --------------------------------------------------------------------------
REAL_LOCAL_ENGINE_EXECUTION_ENABLED = False

_LOCAL_PREFIXO = "local:"


class HarnessError(CouncilModelError):
    """Erro de configuração do harness (fail-closed)."""


class ExecutionFailureCode(str, Enum):
    REAL_EXECUTION_DISABLED = "REAL_EXECUTION_DISABLED"
    REAL_EXECUTION_NOT_IMPLEMENTED = "REAL_EXECUTION_NOT_IMPLEMENTED"
    REAL_EXECUTION_FORBIDDEN_BY_PHASE = "REAL_EXECUTION_FORBIDDEN_BY_PHASE"
    REAL_EXECUTION_ENGINE_NOT_LOCAL = "REAL_EXECUTION_ENGINE_NOT_LOCAL"
    REAL_EXECUTION_PRIVATE_MODE_NO_PERSIST = "REAL_EXECUTION_PRIVATE_MODE_NO_PERSIST"


@dataclass(frozen=True)
class LocalExecutionFailure:
    code: ExecutionFailureCode
    reason: str = ""


# --------------------------- pedido ---------------------------

@dataclass
class LocalExecutionRequest:
    engine_id: str
    adapter_id: str = "dryrun:local-adapter"
    prompt_chars: int = 0
    mode: CouncilMode = CouncilMode.BALANCED
    risk_level: CouncilRiskLevel = CouncilRiskLevel.A1
    private_mode: bool = False
    contains_sensitive_data: bool = False

    def __post_init__(self):
        if not isinstance(self.engine_id, str) or not self.engine_id.startswith(_LOCAL_PREFIXO):
            raise HarnessError(f"engine_id deve começar por '{_LOCAL_PREFIXO}'")
        if not self.adapter_id:
            raise HarnessError("adapter_id obrigatório")
        self.mode = _coerce_enum(CouncilMode, self.mode, "mode")
        self.risk_level = _coerce_enum(CouncilRiskLevel, self.risk_level, "risk_level")
        if not isinstance(self.prompt_chars, int) or self.prompt_chars < 0:
            raise HarnessError("prompt_chars deve ser inteiro >= 0")

    @classmethod
    def from_prompt(cls, prompt: str, engine_id: str, **kw) -> "LocalExecutionRequest":
        """Constrói guardando SÓ o tamanho — o prompt bruto é descartado."""
        return cls(engine_id=engine_id, prompt_chars=len(prompt or ""), **kw)

    @property
    def persist_allowed(self) -> bool:
        return not self.private_mode

    def to_dict(self) -> dict:
        return {"schema": "nomos.council.local_execution_request.v1",
                "engine_id": self.engine_id, "adapter_id": self.adapter_id,
                "prompt_chars": self.prompt_chars, "mode": self.mode.value,
                "risk_level": self.risk_level.value, "private_mode": self.private_mode,
                "contains_sensitive_data": self.contains_sensitive_data}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)

    def __repr__(self) -> str:   # não há prompt aqui; só metadados
        return (f"LocalExecutionRequest(engine_id={self.engine_id!r}, "
                f"adapter_id={self.adapter_id!r}, prompt_chars={self.prompt_chars}, "
                f"private_mode={self.private_mode})")


# --------------------------- registro de tentativa ---------------------------

@dataclass
class LocalExecutionAttemptRecord:
    engine_id: str
    adapter_id: str
    block_reason: str
    private_mode: bool = False
    would_execute: bool = True     # tentativa CONCEITUAL de execução real
    executed: bool = False         # nunca executa
    blocked: bool = True           # sempre bloqueado

    def __post_init__(self):
        # invariantes inegociáveis
        self.executed = False
        self.blocked = True

    @property
    def persist_allowed(self) -> bool:
        return not self.private_mode

    def to_dict(self) -> dict:
        return {"schema": "nomos.council.local_execution_attempt.v1",
                "engine_id": self.engine_id, "adapter_id": self.adapter_id,
                "would_execute": self.would_execute, "executed": self.executed,
                "blocked": self.blocked, "block_reason": self.block_reason,
                "private_mode": self.private_mode,
                "persist_allowed": self.persist_allowed}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)

    def __repr__(self) -> str:
        return (f"LocalExecutionAttemptRecord(engine_id={self.engine_id!r}, "
                f"executed={self.executed}, blocked={self.blocked}, "
                f"block_reason={self.block_reason!r}, "
                f"persist_allowed={self.persist_allowed})")


# --------------------------- resultado ---------------------------

@dataclass
class LocalExecutionResult:
    failure_code: ExecutionFailureCode
    attempt: LocalExecutionAttemptRecord
    allowed: bool = False     # execução real nunca é permitida nesta fase
    executed: bool = False    # nunca executa
    candidate: None = None    # sempre None

    def __post_init__(self):
        self.allowed = False
        self.executed = False
        self.candidate = None

    def to_dict(self) -> dict:
        return {"schema": "nomos.council.local_execution_result.v1",
                "allowed": self.allowed, "executed": self.executed,
                "failure_code": self.failure_code.value,
                "candidate": None, "attempt": self.attempt.to_dict()}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)

    def __repr__(self) -> str:
        return (f"LocalExecutionResult(allowed={self.allowed}, "
                f"executed={self.executed}, failure_code={self.failure_code}, "
                f"has_candidate={self.candidate is not None})")


# --------------------------- harness ---------------------------

class LocalExecutionHarness:
    """Harness de execução local. SEMPRE fail-closed: nada é executado.

    Nunca chama motor/subprocess/rede/FS/env/policy/vault/audit; sem time/random.
    Não expõe API para ativar execução real."""

    def execute(self, request) -> LocalExecutionResult:
        engine_id = getattr(request, "engine_id", "")
        adapter_id = getattr(request, "adapter_id", "dryrun:local-adapter")
        private_mode = bool(getattr(request, "private_mode", False))

        # motor não-local é ainda pior que desligado — barra primeiro
        if not (isinstance(engine_id, str) and engine_id.startswith(_LOCAL_PREFIXO)):
            code = ExecutionFailureCode.REAL_EXECUTION_ENGINE_NOT_LOCAL
        elif not REAL_LOCAL_ENGINE_EXECUTION_ENABLED:
            # caminho principal: a trava está literalmente desligada
            code = ExecutionFailureCode.REAL_EXECUTION_DISABLED
        else:                       # pragma: no cover - inalcançável (flag=False)
            code = ExecutionFailureCode.REAL_EXECUTION_NOT_IMPLEMENTED

        attempt = LocalExecutionAttemptRecord(
            engine_id=str(engine_id), adapter_id=str(adapter_id),
            block_reason=code.value, private_mode=private_mode)
        return LocalExecutionResult(failure_code=code, attempt=attempt)


def real_execution_enabled() -> bool:
    """Leitura (somente leitura) da trava. Não há setter — é sempre False."""
    return REAL_LOCAL_ENGINE_EXECUTION_ENABLED
