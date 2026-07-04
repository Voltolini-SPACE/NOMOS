"""NOMOS Motor Council — integração de motores LOCAIS (Fase MC3).

Camada mínima, por CONTRATO, que troca apenas a origem dos candidatos: em vez de
`SimulatedEngineFixture`, os candidatos vêm de um `LocalCandidateProvider` que
gera respostas por motores LOCAIS elegíveis. Nesta fase:

- **sem cloud, sem rede externa, sem SDK remoto** (nem OpenAI/Anthropic/Ollama);
- juízes, árbitro e Policy Gate continuam SIMULADOS (MC2);
- sem policy/vault/audit reais, sem persistência, sem CLI/chat;
- fail-closed: sem motor local elegível ⇒ `failure_code`, nunca crash;
- um motor que declare cloud/rede é INELEGÍVEL (nunca é usado).

Módulo puro (stdlib + modelos do council). A pureza é provada por teste (AST).
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
from nomos.council.simulator import (
    OfflineCouncilResult,
    OfflineCouncilSimulator,
)

_LOCAL_PREFIXO = "local:"
_ALFABETO = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


class LocalEngineError(CouncilModelError):
    """Erro de configuração da camada de motor local (fail-closed)."""


# --------------------------- descritor de motor ---------------------------

@dataclass
class LocalEngineDescriptor:
    """Descreve um motor LOCAL candidato. `engine_id` deve começar por 'local:'.

    Os flags de segurança podem ser representados, mas um motor com cloud=True,
    network_required=True ou local_only=False é INELEGÍVEL (nunca é usado)."""
    engine_id: str
    modality: str = "text"
    local_only: bool = True
    cloud: bool = False
    network_required: bool = False
    supports_sensitive_data: bool = True

    def __post_init__(self):
        if not isinstance(self.engine_id, str) or not self.engine_id.startswith(_LOCAL_PREFIXO):
            raise LocalEngineError(
                f"engine_id deve começar por '{_LOCAL_PREFIXO}': {self.engine_id!r}")

    @property
    def is_eligible(self) -> bool:
        """Elegível só se for local puro: sem cloud, sem rede, local_only."""
        return (self.engine_id.startswith(_LOCAL_PREFIXO)
                and self.local_only is True
                and self.cloud is False
                and self.network_required is False)

    def eligibility(self) -> "LocalEngineEligibility":
        if self.is_eligible:
            return LocalEngineEligibility(True, "motor local elegível")
        motivos = []
        if self.cloud:
            motivos.append("declara cloud")
        if self.network_required:
            motivos.append("exige rede")
        if not self.local_only:
            motivos.append("não é local_only")
        return LocalEngineEligibility(False, "; ".join(motivos) or "inelegível")


@dataclass(frozen=True)
class LocalEngineEligibility:
    eligible: bool
    reason: str


@dataclass(frozen=True)
class LocalEngineFailure:
    """Falha da camada local, mapeada a um CouncilFailureCode."""
    code: CouncilFailureCode
    reason: str = ""


# --------------------------- pedido / resultado ---------------------------

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
            raise LocalEngineError("prompt obrigatório")
        self.mode = _coerce_enum(CouncilMode, self.mode, "mode")
        self.risk_level = _coerce_enum(CouncilRiskLevel, self.risk_level, "risk_level")
        if not isinstance(self.max_candidates, int) or self.max_candidates < 1:
            raise LocalEngineError("max_candidates deve ser inteiro >= 1")

    # cloud NUNCA é permitida nesta fase (nem por dado sensível, nem nunca)
    @property
    def cloud_allowed(self) -> bool:
        return False

    @property
    def persist_allowed(self) -> bool:
        return not self.private_mode

    @property
    def local_only(self) -> bool:
        return True   # MC3 é local-only por definição (paranoid inclusive)

    def __repr__(self) -> str:   # nunca vaza o prompt
        return (f"LocalCandidateRequest(mode={self.mode.value}, "
                f"risk_level={self.risk_level.value}, "
                f"private_mode={self.private_mode}, "
                f"max_candidates={self.max_candidates}, "
                f"prompt=<{len(self.prompt)} chars>)")


@dataclass
class LocalCandidateResult:
    candidates: list = field(default_factory=list)
    failure_code: CouncilFailureCode | None = None
    warnings: list = field(default_factory=list)

    # sem campo de prompt ⇒ prompt nunca entra aqui; repr dos candidatos redige conteúdo
    def __repr__(self) -> str:
        return (f"LocalCandidateResult(candidates=<{len(self.candidates)}>, "
                f"failure_code={self.failure_code}, warnings={self.warnings})")


# --------------------------- contrato do provider ---------------------------

@runtime_checkable
class LocalCandidateProvider(Protocol):
    """Provedor de candidatos por motores LOCAIS. Nunca usa rede/cloud/FS."""

    def list_engines(self) -> list[LocalEngineDescriptor]:
        ...

    def generate(self, request: LocalCandidateRequest) -> LocalCandidateResult:
        ...


# --------------------------- provider determinístico (teste) ---------------------------

class DeterministicLocalCandidateProvider:
    """Provider FAKE e determinístico p/ validar o contrato local.

    Não chama motor real, rede, filesystem nem env. Produz uma resposta fixa por
    motor local elegível. Motores cloud/rede/não-local são ignorados (inelegíveis)."""

    def __init__(self, engines: list[LocalEngineDescriptor] | None = None):
        # None ⇒ usa os motores mock padrão; [] ⇒ explicitamente SEM motor.
        if engines is None:
            engines = [LocalEngineDescriptor(engine_id="local:mock-a"),
                       LocalEngineDescriptor(engine_id="local:mock-b")]
        self._engines = list(engines)

    def list_engines(self) -> list[LocalEngineDescriptor]:
        return list(self._engines)

    def generate(self, request: LocalCandidateRequest) -> LocalCandidateResult:
        elegiveis = [e for e in self._engines if e.is_eligible]
        warnings = [f"motor inelegível ignorado: {e.engine_id} "
                    f"({e.eligibility().reason})"
                    for e in self._engines if not e.is_eligible]
        if not elegiveis:
            return LocalCandidateResult(
                candidates=[],
                failure_code=CouncilFailureCode.NO_ELIGIBLE_LOCAL_ENGINE,
                warnings=warnings)
        usados = elegiveis[: request.max_candidates]
        candidates = []
        for i, eng in enumerate(usados):
            # conteúdo fixo determinístico — NUNCA o prompt do usuário
            candidates.append(AnswerCandidate(
                candidate_id=f"cand_{i}", engine_id=eng.engine_id,
                content=f"[local] resposta determinística do motor {eng.engine_id}",
                metadata={"modality": eng.modality}))
        return LocalCandidateResult(candidates=candidates, failure_code=None,
                                    warnings=warnings)


# --------------------------- integração com o simulador ---------------------------

def run_offline_council_with_local_candidates(
        request: LocalCandidateRequest,
        provider: LocalCandidateProvider,
        judge_fixtures: list,
        gate=None,
        council_enabled: bool = True) -> OfflineCouncilResult:
    """MC3: candidatos de motores LOCAIS + juízes/árbitro/gate SIMULADOS.

    Só troca a origem dos candidatos; todo o resto é o pipeline puro do MC2.
    Fail-closed: se o provider falhar, o resultado carrega o `failure_code`."""
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
