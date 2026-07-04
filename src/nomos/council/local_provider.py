"""NOMOS Motor Council — contrato de provedor de candidatos LOCAIS (Fase MC3).

Camada mínima e por CONTRATO para, no futuro, motores locais reais gerarem
candidatos. **Nesta fase NÃO há motor real**: apenas o contrato e um provider
determinístico de teste. Regras invioláveis:

- só motores `local:` (local_only, sem cloud, sem rede) são elegíveis;
- cloud/rede ⇒ recusa fail-closed (`CLOUD_BLOCKED_BY_LOCAL_LOCK`);
- dado sensível exige motor que suporte dado sensível, senão recusa
  (`SENSITIVE_DATA_CLOUD_DENIED`);
- sem motor elegível ⇒ `NO_ELIGIBLE_LOCAL_ENGINE`;
- o prompt NUNCA é persistido, logado, ou embutido no conteúdo gerado;
- juízes, árbitro e Policy Gate continuam SIMULADOS (MC2).

Módulo puro (stdlib + modelos/simulador do council). Sem rede, cloud, SDK
remoto, subprocess, threading, asyncio, FS, env, tempo real ou random. Pureza
provada por teste (AST).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from nomos.council.models import (
    AnswerCandidate,
    CouncilFailureCode,
    CouncilMode,
    CouncilModelError,
    CouncilRiskLevel,
    _coerce_enum,
)
from nomos.council.simulator import OfflineCouncilResult, OfflineCouncilSimulator

_LOCAL_PREFIXO = "local:"
_ALFABETO = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


class LocalProviderError(CouncilModelError):
    """Erro de configuração da camada de provider local (fail-closed)."""


# --------------------------- descritor de motor ---------------------------

@dataclass
class LocalEngineDescriptor:
    """Descreve um motor local candidato. `engine_id` deve começar por 'local:'.

    Flags inseguros (cloud/rede/não-local) podem ser representados, mas tornam o
    motor INELEGÍVEL — nunca é usado."""
    engine_id: str
    modality: str = "text"
    local_only: bool = True
    cloud: bool = False
    network_required: bool = False
    supports_sensitive_data: bool = True

    def __post_init__(self):
        if not isinstance(self.engine_id, str) or not self.engine_id.startswith(_LOCAL_PREFIXO):
            raise LocalProviderError(
                f"engine_id deve começar por '{_LOCAL_PREFIXO}': {self.engine_id!r}")

    @property
    def is_local_safe(self) -> bool:
        """Só local puro: prefixo local:, local_only, sem cloud, sem rede."""
        return (self.engine_id.startswith(_LOCAL_PREFIXO)
                and self.local_only is True
                and self.cloud is False
                and self.network_required is False)

    @property
    def is_eligible(self) -> bool:
        return self.is_local_safe

    def can_handle(self, contains_sensitive_data: bool) -> bool:
        """Elegível E capaz de lidar com o dado (sensível exige suporte)."""
        if not self.is_local_safe:
            return False
        if contains_sensitive_data and not self.supports_sensitive_data:
            return False
        return True

    def to_dict(self) -> dict:
        return {"schema": "nomos.council.local_engine.v1", "engine_id": self.engine_id,
                "modality": self.modality, "local_only": self.local_only,
                "cloud": self.cloud, "network_required": self.network_required,
                "supports_sensitive_data": self.supports_sensitive_data}


@dataclass(frozen=True)
class LocalProviderFailure:
    """Falha do provider local, mapeada a um CouncilFailureCode."""
    code: CouncilFailureCode
    reason: str = ""


# --------------------------- pedido ---------------------------

@dataclass
class LocalCandidateRequest:
    prompt: str = field(repr=False)
    mode: CouncilMode = CouncilMode.BALANCED
    risk_level: CouncilRiskLevel = CouncilRiskLevel.A1
    private_mode: bool = False
    contains_sensitive_data: bool = False
    max_candidates: int = 3

    def __post_init__(self):
        if not self.prompt:
            raise LocalProviderError("prompt obrigatório")
        self.mode = _coerce_enum(CouncilMode, self.mode, "mode")
        self.risk_level = _coerce_enum(CouncilRiskLevel, self.risk_level, "risk_level")
        if not isinstance(self.max_candidates, int) or self.max_candidates < 1:
            raise LocalProviderError("max_candidates deve ser inteiro >= 1")

    @property
    def cloud_allowed(self) -> bool:
        return False   # MC3 nunca permite cloud (nem por dado sensível)

    @property
    def persist_allowed(self) -> bool:
        return not self.private_mode

    @property
    def local_only(self) -> bool:
        return True    # local-only por definição (paranoid inclusive)

    def to_dict(self) -> dict:
        """Serializável — o prompt NÃO entra aqui (evita vazamento)."""
        return {"schema": "nomos.council.local_request.v1", "mode": self.mode.value,
                "risk_level": self.risk_level.value, "private_mode": self.private_mode,
                "contains_sensitive_data": self.contains_sensitive_data,
                "max_candidates": self.max_candidates,
                "prompt_len": len(self.prompt)}

    def __repr__(self) -> str:   # nunca vaza o prompt
        return (f"LocalCandidateRequest(mode={self.mode.value}, "
                f"risk_level={self.risk_level.value}, private_mode={self.private_mode}, "
                f"contains_sensitive_data={self.contains_sensitive_data}, "
                f"max_candidates={self.max_candidates}, prompt=<{len(self.prompt)} chars>)")


# --------------------------- resultado ---------------------------

@dataclass
class LocalCandidateResult:
    candidates: list = field(default_factory=list)
    failure_code: CouncilFailureCode | None = None
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"schema": "nomos.council.local_result.v1",
                "candidates": [c.to_dict() for c in self.candidates],
                "failure_code": self.failure_code.value if self.failure_code else None,
                "warnings": list(self.warnings)}

    def __repr__(self) -> str:   # sem prompt nem conteúdo integral
        return (f"LocalCandidateResult(candidates=<{len(self.candidates)}>, "
                f"failure_code={self.failure_code}, warnings=<{len(self.warnings)}>)")


# --------------------------- contrato do provider ---------------------------

@runtime_checkable
class LocalCandidateProvider(Protocol):
    """Provedor de candidatos por motores LOCAIS. Nunca usa rede/cloud/FS/env."""

    def list_engines(self) -> list[LocalEngineDescriptor]:
        ...

    def generate(self, request: LocalCandidateRequest) -> LocalCandidateResult:
        ...


def _avaliar(engines, request) -> LocalProviderFailure | None:
    """Escolhe o CouncilFailureCode adequado quando não há motor utilizável."""
    if not engines:
        return LocalProviderFailure(CouncilFailureCode.NO_ELIGIBLE_LOCAL_ENGINE,
                                    "nenhum motor local")
    safe = [e for e in engines if e.is_local_safe]
    if not safe:
        if any(e.cloud or e.network_required for e in engines):
            return LocalProviderFailure(
                CouncilFailureCode.CLOUD_BLOCKED_BY_LOCAL_LOCK,
                "motor declara cloud/rede — bloqueado pelo cadeado local")
        return LocalProviderFailure(CouncilFailureCode.NO_ELIGIBLE_LOCAL_ENGINE,
                                    "nenhum motor local elegível")
    capazes = [e for e in safe if e.can_handle(request.contains_sensitive_data)]
    if not capazes:
        # há motor local, mas o dado é sensível e nenhum suporta
        return LocalProviderFailure(
            CouncilFailureCode.SENSITIVE_DATA_CLOUD_DENIED,
            "dado sensível: nenhum motor local suporta dado sensível")
    return None


# --------------------------- provider determinístico (teste) ---------------------------

class DeterministicLocalCandidateProvider:
    """Provider FAKE e determinístico p/ validar o contrato local.

    Não chama motor real, rede, cloud, filesystem, env; sem tempo real, sem
    random. Conteúdo fixo por motor — NUNCA o prompt do usuário."""

    def __init__(self, engines: list[LocalEngineDescriptor] | None = None):
        # None ⇒ usa os mocks padrão; [] ⇒ explicitamente SEM motor.
        if engines is None:
            engines = [LocalEngineDescriptor(engine_id="local:mock-a"),
                       LocalEngineDescriptor(engine_id="local:mock-b")]
        self._engines = list(engines)

    def list_engines(self) -> list[LocalEngineDescriptor]:
        return list(self._engines)

    def generate(self, request: LocalCandidateRequest) -> LocalCandidateResult:
        warnings = [f"motor inelegível ignorado: {e.engine_id}"
                    for e in self._engines if not e.is_local_safe]
        falha = _avaliar(self._engines, request)
        if falha is not None:
            return LocalCandidateResult(candidates=[], failure_code=falha.code,
                                        warnings=warnings + [falha.reason])
        capazes = [e for e in self._engines
                   if e.can_handle(request.contains_sensitive_data)]
        usados = capazes[: request.max_candidates]
        candidates = []
        for i, eng in enumerate(usados):
            candidates.append(AnswerCandidate(
                candidate_id=f"cand_{i}", engine_id=eng.engine_id,
                content=f"[local] resposta determinística {i + 1} do motor {eng.engine_id}",
                metadata={"modality": eng.modality}))
        return LocalCandidateResult(candidates=candidates, failure_code=None,
                                    warnings=warnings)


# --------------------------- integração com o simulador ---------------------------

def run_offline_council_with_local_provider(
        request: LocalCandidateRequest,
        provider: LocalCandidateProvider,
        judge_fixtures: list,
        gate=None,
        council_enabled: bool = True) -> OfflineCouncilResult:
    """MC3: candidatos de um provider LOCAL + juízes/árbitro/gate SIMULADOS.

    Só troca a origem dos candidatos; todo o resto é o pipeline puro do MC2.
    Fail-closed: se o provider falhar, o `failure_code` é propagado e a decisão
    do árbitro fica bloqueada."""
    local = provider.generate(request)

    candidates = list(local.candidates)
    alias_por_candidato: dict[str, str] = {}
    engine_por_alias: dict[str, str] = {}
    for i, c in enumerate(candidates):
        alias = _ALFABETO[i] if i < len(_ALFABETO) else f"C{i}"
        alias_por_candidato[c.candidate_id] = alias
        engine_por_alias[alias] = c.engine_id

    sim = OfflineCouncilSimulator()
    return sim.run_with_candidates(
        candidates=candidates, alias_por_candidato=alias_por_candidato,
        engine_por_alias=engine_por_alias, judge_fixtures=judge_fixtures,
        mode=request.mode, risk_level=request.risk_level, local_only=True,
        private_mode=request.private_mode,
        contains_sensitive_data=request.contains_sensitive_data,
        council_enabled=council_enabled, gate=gate,
        provider_failure=local.failure_code)
