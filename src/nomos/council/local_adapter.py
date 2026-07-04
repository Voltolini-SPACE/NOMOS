"""NOMOS Motor Council — adaptador de motor local em SPEC/DRY-RUN (Fase MC4).

Representa COMO um motor local real seria chamado no futuro, mas **não executa
nada**: só produz plano de execução e um ensaio (dry-run) determinístico que
prova o isolamento (sem rede, subprocess, filesystem, env, cloud, loopback)
ANTES de qualquer execução real.

Invariantes desta fase:
- `would_execute=false` SEMPRE; `dry_run=true` SEMPRE;
- perfil de isolamento nega TUDO por padrão; qualquer permissão ⇒ erro/bloqueio;
- política do adaptador é `dry_run_only=true`, `local_only=true`, tudo negado;
- motor não-local/cloud/rede ⇒ bloqueado com código próprio (fail-closed);
- prompt NUNCA entra no plano, resultado, warnings, conteúdo ou repr.

Módulo puro (stdlib + modelos/provider do council). Sem rede, cloud, SDK remoto,
subprocess, threading, asyncio, FS, env, tempo real ou random. Pureza provada
por teste (AST).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

from nomos.council.models import (
    AnswerCandidate,
    CouncilFailureCode,
    CouncilModelError,
)
from nomos.council.local_provider import (
    LocalCandidateRequest,
    LocalCandidateResult,
    LocalEngineDescriptor,
)

_LOCAL_PREFIXO = "local:"
_ADAPTER_ID = "dryrun:local-adapter"


class AdapterError(CouncilModelError):
    """Erro de configuração do adaptador (fail-closed)."""


# --------------------------- códigos de falha ---------------------------

class AdapterFailureCode(str, Enum):
    ADAPTER_DRY_RUN_ONLY = "ADAPTER_DRY_RUN_ONLY"
    ADAPTER_ENGINE_NOT_LOCAL = "ADAPTER_ENGINE_NOT_LOCAL"
    ADAPTER_CLOUD_DENIED = "ADAPTER_CLOUD_DENIED"
    ADAPTER_NETWORK_DENIED = "ADAPTER_NETWORK_DENIED"
    ADAPTER_SUBPROCESS_DENIED = "ADAPTER_SUBPROCESS_DENIED"
    ADAPTER_FILESYSTEM_DENIED = "ADAPTER_FILESYSTEM_DENIED"
    ADAPTER_ENV_DENIED = "ADAPTER_ENV_DENIED"
    ADAPTER_LOOPBACK_DENIED = "ADAPTER_LOOPBACK_DENIED"
    ADAPTER_PROMPT_TOO_LARGE = "ADAPTER_PROMPT_TOO_LARGE"
    ADAPTER_ENGINE_INELIGIBLE = "ADAPTER_ENGINE_INELIGIBLE"


# Mapeamento para o CouncilFailureCode usado pelo pipeline/provider.
_PARA_COUNCIL = {
    AdapterFailureCode.ADAPTER_ENGINE_NOT_LOCAL: CouncilFailureCode.NO_ELIGIBLE_LOCAL_ENGINE,
    AdapterFailureCode.ADAPTER_ENGINE_INELIGIBLE: CouncilFailureCode.NO_ELIGIBLE_LOCAL_ENGINE,
    AdapterFailureCode.ADAPTER_CLOUD_DENIED: CouncilFailureCode.CLOUD_BLOCKED_BY_LOCAL_LOCK,
    AdapterFailureCode.ADAPTER_NETWORK_DENIED: CouncilFailureCode.CLOUD_BLOCKED_BY_LOCAL_LOCK,
    AdapterFailureCode.ADAPTER_SUBPROCESS_DENIED: CouncilFailureCode.CLOUD_BLOCKED_BY_LOCAL_LOCK,
    AdapterFailureCode.ADAPTER_FILESYSTEM_DENIED: CouncilFailureCode.CLOUD_BLOCKED_BY_LOCAL_LOCK,
    AdapterFailureCode.ADAPTER_ENV_DENIED: CouncilFailureCode.CLOUD_BLOCKED_BY_LOCAL_LOCK,
    AdapterFailureCode.ADAPTER_LOOPBACK_DENIED: CouncilFailureCode.CLOUD_BLOCKED_BY_LOCAL_LOCK,
    AdapterFailureCode.ADAPTER_PROMPT_TOO_LARGE: CouncilFailureCode.ENGINE_FAILED,
    AdapterFailureCode.ADAPTER_DRY_RUN_ONLY: CouncilFailureCode.NO_ELIGIBLE_LOCAL_ENGINE,
}


def council_failure_for(code: AdapterFailureCode) -> CouncilFailureCode:
    return _PARA_COUNCIL[code]


@dataclass(frozen=True)
class LocalAdapterFailure:
    code: AdapterFailureCode
    reason: str = ""

    @property
    def council_code(self) -> CouncilFailureCode:
        return _PARA_COUNCIL[self.code]


# --------------------------- perfil de isolamento ---------------------------

@dataclass
class LocalEngineIsolationProfile:
    """Nega TUDO por padrão. Qualquer permissão é proibida nesta fase."""
    network_allowed: bool = False
    subprocess_allowed: bool = False
    filesystem_allowed: bool = False
    env_allowed: bool = False
    cloud_allowed: bool = False
    loopback_allowed: bool = False

    def __post_init__(self):
        proibidos = [n for n in ("network_allowed", "subprocess_allowed",
                                 "filesystem_allowed", "env_allowed",
                                 "cloud_allowed", "loopback_allowed")
                     if getattr(self, n)]
        if proibidos:
            raise AdapterError(
                f"perfil de isolamento inválido nesta fase (dry-run): "
                f"{', '.join(proibidos)} devem ser false")

    def to_dict(self) -> dict:
        return {"schema": "nomos.council.local_isolation.v1",
                "network_allowed": self.network_allowed,
                "subprocess_allowed": self.subprocess_allowed,
                "filesystem_allowed": self.filesystem_allowed,
                "env_allowed": self.env_allowed,
                "cloud_allowed": self.cloud_allowed,
                "loopback_allowed": self.loopback_allowed}


# --------------------------- política do adaptador ---------------------------

@dataclass
class LocalEngineAdapterPolicy:
    dry_run_only: bool = True
    local_only: bool = True
    allow_cloud: bool = False
    allow_network: bool = False
    allow_subprocess: bool = False
    allow_filesystem: bool = False
    allow_env: bool = False
    allow_loopback: bool = False
    max_prompt_chars: int = 8000
    max_output_chars: int = 4000

    def __post_init__(self):
        if self.dry_run_only is not True:
            raise AdapterError("dry_run_only deve ser true nesta fase")
        if self.local_only is not True:
            raise AdapterError("local_only deve ser true")
        permitidos = [n for n in ("allow_cloud", "allow_network", "allow_subprocess",
                                  "allow_filesystem", "allow_env", "allow_loopback")
                      if getattr(self, n)]
        if permitidos:
            raise AdapterError(
                f"política inválida nesta fase: {', '.join(permitidos)} devem ser false")
        if not (isinstance(self.max_prompt_chars, int) and self.max_prompt_chars > 0):
            raise AdapterError("max_prompt_chars deve ser inteiro > 0")
        if not (isinstance(self.max_output_chars, int) and self.max_output_chars > 0):
            raise AdapterError("max_output_chars deve ser inteiro > 0")

    def to_dict(self) -> dict:
        return {"schema": "nomos.council.local_adapter_policy.v1",
                "dry_run_only": self.dry_run_only, "local_only": self.local_only,
                "allow_cloud": self.allow_cloud, "allow_network": self.allow_network,
                "allow_subprocess": self.allow_subprocess,
                "allow_filesystem": self.allow_filesystem, "allow_env": self.allow_env,
                "allow_loopback": self.allow_loopback,
                "max_prompt_chars": self.max_prompt_chars,
                "max_output_chars": self.max_output_chars}


# --------------------------- plano de execução ---------------------------

@dataclass
class LocalEngineExecutionPlan:
    engine_id: str
    prompt_chars: int
    expected_output_chars: int
    isolation: dict
    policy: dict
    adapter_id: str = _ADAPTER_ID
    dry_run: bool = True
    would_execute: bool = False
    blocked: bool = False
    block_reason: str | None = None

    def __post_init__(self):
        # invariantes inegociáveis desta fase
        self.dry_run = True
        self.would_execute = False
        if not self.adapter_id.startswith("dryrun:"):
            raise AdapterError("adapter_id deve começar por 'dryrun:'")
        if not self.blocked and not self.engine_id.startswith(_LOCAL_PREFIXO):
            raise AdapterError("plano válido exige engine_id 'local:'")
        if not isinstance(self.prompt_chars, int) or self.prompt_chars < 0:
            raise AdapterError("prompt_chars deve ser inteiro >= 0")

    def to_dict(self) -> dict:
        return {"schema": "nomos.council.local_execution_plan.v1",
                "engine_id": self.engine_id, "adapter_id": self.adapter_id,
                "dry_run": self.dry_run, "would_execute": self.would_execute,
                "prompt_chars": self.prompt_chars,
                "expected_output_chars": self.expected_output_chars,
                "isolation": self.isolation, "policy": self.policy,
                "blocked": self.blocked, "block_reason": self.block_reason}

    def __repr__(self) -> str:   # só metadados; nunca o prompt
        return (f"LocalEngineExecutionPlan(engine_id={self.engine_id!r}, "
                f"adapter_id={self.adapter_id!r}, dry_run={self.dry_run}, "
                f"would_execute={self.would_execute}, prompt_chars={self.prompt_chars}, "
                f"blocked={self.blocked})")


# --------------------------- resultado do dry-run ---------------------------

@dataclass
class LocalEngineDryRunResult:
    plan: LocalEngineExecutionPlan
    candidate: AnswerCandidate | None = None
    allowed: bool = True
    failure_code: AdapterFailureCode | None = None
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"schema": "nomos.council.local_dry_run_result.v1",
                "plan": self.plan.to_dict(),
                "candidate": self.candidate.to_dict() if self.candidate else None,
                "allowed": self.allowed,
                "failure_code": self.failure_code.value if self.failure_code else None,
                "warnings": list(self.warnings)}

    def __repr__(self) -> str:   # sem prompt/conteúdo integral
        return (f"LocalEngineDryRunResult(allowed={self.allowed}, "
                f"failure_code={self.failure_code}, "
                f"has_candidate={self.candidate is not None}, "
                f"warnings=<{len(self.warnings)}>)")


# --------------------------- contrato do adaptador ---------------------------

@runtime_checkable
class LocalEngineAdapter(Protocol):
    def plan(self, descriptor: LocalEngineDescriptor,
             request: LocalCandidateRequest) -> LocalEngineExecutionPlan:
        ...

    def dry_run(self, descriptor: LocalEngineDescriptor,
                request: LocalCandidateRequest) -> LocalEngineDryRunResult:
        ...


# --------------------------- adaptador dry-run ---------------------------

class DryRunLocalEngineAdapter:
    """Adaptador de DRY-RUN. Nunca executa motor/rede/subprocess/FS/env.

    Determinístico: sem tempo real, sem random."""

    def __init__(self, policy: LocalEngineAdapterPolicy | None = None,
                 isolation: LocalEngineIsolationProfile | None = None):
        self.policy = policy or LocalEngineAdapterPolicy()
        self.isolation = isolation or LocalEngineIsolationProfile()

    def _avaliar(self, descriptor: LocalEngineDescriptor,
                 request: LocalCandidateRequest) -> LocalAdapterFailure | None:
        if not descriptor.engine_id.startswith(_LOCAL_PREFIXO):
            return LocalAdapterFailure(AdapterFailureCode.ADAPTER_ENGINE_NOT_LOCAL,
                                       "engine_id não é local:")
        if descriptor.cloud:
            return LocalAdapterFailure(AdapterFailureCode.ADAPTER_CLOUD_DENIED,
                                       "motor declara cloud")
        if descriptor.network_required:
            return LocalAdapterFailure(AdapterFailureCode.ADAPTER_NETWORK_DENIED,
                                       "motor exige rede")
        if not descriptor.local_only:
            return LocalAdapterFailure(AdapterFailureCode.ADAPTER_ENGINE_INELIGIBLE,
                                       "motor não é local_only")
        if len(request.prompt) > self.policy.max_prompt_chars:
            return LocalAdapterFailure(AdapterFailureCode.ADAPTER_PROMPT_TOO_LARGE,
                                       "prompt excede max_prompt_chars")
        return None

    def plan(self, descriptor: LocalEngineDescriptor,
             request: LocalCandidateRequest) -> LocalEngineExecutionPlan:
        falha = self._avaliar(descriptor, request)
        expected = min(64, self.policy.max_output_chars)   # determinístico
        return LocalEngineExecutionPlan(
            engine_id=descriptor.engine_id, prompt_chars=len(request.prompt),
            expected_output_chars=expected, isolation=self.isolation.to_dict(),
            policy=self.policy.to_dict(),
            blocked=falha is not None,
            block_reason=(falha.code.value if falha else None))

    def dry_run(self, descriptor: LocalEngineDescriptor,
                request: LocalCandidateRequest) -> LocalEngineDryRunResult:
        plano = self.plan(descriptor, request)
        falha = self._avaliar(descriptor, request)
        if falha is not None:
            return LocalEngineDryRunResult(
                plan=plano, candidate=None, allowed=False,
                failure_code=falha.code, warnings=[falha.reason])
        # candidato SIMULADO (nunca inclui o prompt)
        cand = AnswerCandidate(
            candidate_id="dry_cand_0", engine_id=descriptor.engine_id,
            content=f"[dry-run] resposta local simulada do motor {descriptor.engine_id}",
            metadata={"adapter": _ADAPTER_ID, "dry_run": True})
        return LocalEngineDryRunResult(plan=plano, candidate=cand, allowed=True,
                                       failure_code=None, warnings=[])


# --------------------------- provider via adaptador dry-run ---------------------------

class DryRunAdapterCandidateProvider:
    """Provider (contrato MC3) que usa o adaptador DRY-RUN. Sem execução real."""

    def __init__(self, engines: list[LocalEngineDescriptor] | None = None,
                 adapter: DryRunLocalEngineAdapter | None = None):
        if engines is None:
            engines = [LocalEngineDescriptor("local:mock-a"),
                       LocalEngineDescriptor("local:mock-b")]
        self._engines = list(engines)
        self.adapter = adapter or DryRunLocalEngineAdapter()

    def list_engines(self) -> list[LocalEngineDescriptor]:
        return list(self._engines)

    def generate(self, request: LocalCandidateRequest) -> LocalCandidateResult:
        if not self._engines:
            return LocalCandidateResult(
                candidates=[], failure_code=CouncilFailureCode.NO_ELIGIBLE_LOCAL_ENGINE,
                warnings=["nenhum motor local"])
        candidates, warnings = [], []
        ultima_falha: LocalAdapterFailure | None = None
        for eng in self._engines:
            r = self.adapter.dry_run(eng, request)
            if r.allowed and r.candidate is not None:
                # id determinístico e prefixado, preservando ordem
                c = r.candidate
                candidates.append(AnswerCandidate(
                    candidate_id=f"dry_cand_{len(candidates)}", engine_id=c.engine_id,
                    content=c.content, metadata=dict(c.metadata)))
            else:
                warnings.extend(r.warnings)
                if r.failure_code is not None:
                    ultima_falha = LocalAdapterFailure(r.failure_code,
                                                       "; ".join(r.warnings))
            if len(candidates) >= request.max_candidates:
                break
        if not candidates:
            council = (ultima_falha.council_code if ultima_falha
                       else CouncilFailureCode.NO_ELIGIBLE_LOCAL_ENGINE)
            return LocalCandidateResult(candidates=[], failure_code=council,
                                        warnings=warnings)
        return LocalCandidateResult(candidates=candidates[: request.max_candidates],
                                    failure_code=None, warnings=warnings)
