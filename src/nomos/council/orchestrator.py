"""NOMOS Motor Council — orquestrador em SPEC/DRY-RUN (Fase MC8).

Compõe, em memória, as camadas já testadas do Council num único fluxo:

    LocalCandidateProvider (MC3/MC4, dry-run)
      -> OfflineCouncilSimulator (MC2)
      -> CouncilPolicyGateDryRun (MC6)
      -> CouncilAuditEnvelopeBuilder (MC7)
      -> CouncilOrchestrationResult

Nesta fase, tudo continua:

    dry_run=true
    no_real_engine=true
    no_real_policy=true
    no_real_audit=true
    no_real_vault=true
    no_persistence=true
    no_network=true
    deterministic=true

O orquestrador NÃO importa o harness de execução real (`local_harness`) — essa
camada nem é referenciada aqui, então não há caminho algum, direto ou indireto,
para execução real através deste módulo. O provider padrão usa o adaptador
DRY-RUN (`DryRunAdapterCandidateProvider` sobre `DryRunLocalEngineAdapter`), que
nunca executa motor/rede/subprocess/FS/env.

Fail-closed por construção: cada etapa do pipeline é registrada num trace
metadata-only (nunca prompt, conteúdo de candidato/final ou engine_id); se
qualquer etapa falhar (ou uma exceção inesperada escapar de um componente
plugável — provider/simulador/gate/audit builder), o resultado fica bloqueado
(`allowed=false`), mas o trace completo continua sendo produzido, na ordem:

    INPUT_VALIDATED -> LOCAL_PROVIDER_EVALUATED -> CANDIDATES_CREATED ->
    SIMULATOR_RAN -> POLICY_GATE_EVALUATED -> FINAL_ENVELOPE_CREATED ->
    AUDIT_ENVELOPE_CREATED -> ORCHESTRATION_COMPLETED | ORCHESTRATION_BLOCKED

O Policy Gate SEMPRE é avaliado antes do envelope final, e o audit envelope
SEMPRE é criado depois do gate — nessa ordem, mesmo quando o resultado é
bloqueado. `private_mode=true` propaga para o envelope final e para todos os
envelopes de auditoria (`persist_allowed=false` em todos).

Módulo puro (stdlib + módulos já dry-run do council). Sem rede, cloud, SDK
remoto, motor real, subprocess, threading, asyncio, FS, env, tempo real ou
random. Nunca chama policy/vault/audit/approval reais. Pureza provada por
teste (AST).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum

from nomos.council.models import (
    CouncilFailureCode,
    CouncilMode,
    CouncilModelError,
    CouncilRiskLevel,
    _coerce_enum,
)
from nomos.council.local_provider import (
    LocalCandidateProvider,
    LocalCandidateRequest,
    LocalCandidateResult,
)
from nomos.council.local_adapter import DryRunAdapterCandidateProvider
from nomos.council.simulator import OfflineCouncilSimulator, SimulatedJudgeFixture
from nomos.council.policy_gate import (
    CouncilGateDecision,
    CouncilGateRequest,
    CouncilPolicyGateDryRun,
    FinalResponseEnvelope,
)
from nomos.council.audit_envelope import (
    CouncilAuditDryRunResult,
    CouncilAuditEnvelopeBuilder,
)

_ALFABETO = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# chaves/valores que NUNCA podem aparecer na metadata de um step (mesma
# disciplina do audit envelope — checagem local, sem importar internals de
# outro módulo, para manter cada módulo independentemente puro/provável).
_SENSITIVE_KEYS_STEP = {
    "prompt", "content", "final_content", "candidate_content", "raw",
    "secret", "token", "api_key", "apikey", "password", "passphrase",
    "credential", "authorization", "bearer", "engine_id", "judge_engine_id",
}
_SENSITIVE_VALUE_MARKS_STEP = ("bearer ", "sk-", "password", "secret", "token",
                              "api_key", "passphrase", "-----begin")


class OrchestratorError(CouncilModelError):
    """Erro de configuração do orquestrador (fail-closed)."""


def _step_metadata_sensivel(metadata: dict) -> str | None:
    def _valor_sensivel(v) -> bool:
        if isinstance(v, str):
            return any(m in v.lower() for m in _SENSITIVE_VALUE_MARKS_STEP)
        if isinstance(v, dict):
            return any(str(k).lower() in _SENSITIVE_KEYS_STEP
                       or _valor_sensivel(x) for k, x in v.items())
        if isinstance(v, (list, tuple, set)):
            return any(_valor_sensivel(x) for x in v)
        return False

    for k, v in (metadata or {}).items():
        if str(k).lower() in _SENSITIVE_KEYS_STEP:
            return f"chave sensível: {k}"
        if _valor_sensivel(v):
            return "valor sensível em metadata"
    return None


# --------------------------- nomes de etapa ---------------------------

class CouncilOrchestrationStepName(str, Enum):
    INPUT_VALIDATED = "INPUT_VALIDATED"
    LOCAL_PROVIDER_EVALUATED = "LOCAL_PROVIDER_EVALUATED"
    CANDIDATES_CREATED = "CANDIDATES_CREATED"
    SIMULATOR_RAN = "SIMULATOR_RAN"
    POLICY_GATE_EVALUATED = "POLICY_GATE_EVALUATED"
    FINAL_ENVELOPE_CREATED = "FINAL_ENVELOPE_CREATED"
    AUDIT_ENVELOPE_CREATED = "AUDIT_ENVELOPE_CREATED"
    ORCHESTRATION_COMPLETED = "ORCHESTRATION_COMPLETED"
    ORCHESTRATION_BLOCKED = "ORCHESTRATION_BLOCKED"


# --------------------------- códigos de falha ---------------------------

class OrchestrationFailureCode(str, Enum):
    ORCH_INPUT_INVALID = "ORCH_INPUT_INVALID"
    ORCH_PROVIDER_FAILED = "ORCH_PROVIDER_FAILED"
    ORCH_NO_CANDIDATES = "ORCH_NO_CANDIDATES"
    ORCH_SIMULATOR_FAILED = "ORCH_SIMULATOR_FAILED"
    ORCH_POLICY_GATE_DENIED = "ORCH_POLICY_GATE_DENIED"
    ORCH_AUDIT_ENVELOPE_DENIED = "ORCH_AUDIT_ENVELOPE_DENIED"
    ORCH_PRIVATE_MODE_PERSIST_DENIED = "ORCH_PRIVATE_MODE_PERSIST_DENIED"
    ORCH_DRY_RUN_ONLY = "ORCH_DRY_RUN_ONLY"
    ORCH_INTERNAL_INVARIANT_FAILED = "ORCH_INTERNAL_INVARIANT_FAILED"


@dataclass(frozen=True)
class CouncilOrchestrationFailure:
    code: OrchestrationFailureCode
    reason: str = ""


# --------------------------- entrada ---------------------------

@dataclass
class CouncilOrchestrationInput:
    session_id: str
    prompt: str = field(repr=False)
    mode: CouncilMode = CouncilMode.BALANCED
    risk_level: CouncilRiskLevel = CouncilRiskLevel.A1
    private_mode: bool = False
    contains_sensitive_data: bool = False
    max_candidates: int = 2

    def __post_init__(self):
        if not self.session_id:
            raise OrchestratorError("session_id obrigatório")
        if not self.prompt:
            raise OrchestratorError("prompt obrigatório")
        self.mode = _coerce_enum(CouncilMode, self.mode, "mode")
        self.risk_level = _coerce_enum(CouncilRiskLevel, self.risk_level, "risk_level")
        if not isinstance(self.max_candidates, int) or self.max_candidates < 1:
            raise OrchestratorError("max_candidates deve ser inteiro >= 1")

    @property
    def local_only(self) -> bool:
        """Sempre local-only, por contrato de todo o pipeline (inclusive paranoid)."""
        return True

    def to_dict(self) -> dict:
        """Serializável — o prompt NUNCA entra aqui (evita vazamento)."""
        return {"schema": "nomos.council.orchestration_input.v1",
                "session_id": self.session_id, "mode": self.mode.value,
                "risk_level": self.risk_level.value, "private_mode": self.private_mode,
                "contains_sensitive_data": self.contains_sensitive_data,
                "max_candidates": self.max_candidates,
                "prompt_chars": len(self.prompt)}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)

    def __repr__(self) -> str:   # nunca vaza o prompt
        return (f"CouncilOrchestrationInput(session_id={self.session_id!r}, "
                f"mode={self.mode.value}, risk_level={self.risk_level.value}, "
                f"private_mode={self.private_mode}, "
                f"contains_sensitive_data={self.contains_sensitive_data}, "
                f"max_candidates={self.max_candidates}, prompt=<{len(self.prompt)} chars>)")


# --------------------------- etapa do trace ---------------------------

@dataclass
class CouncilOrchestrationStep:
    name: CouncilOrchestrationStepName
    ok: bool = True
    failure_code: OrchestrationFailureCode | None = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        self.name = _coerce_enum(CouncilOrchestrationStepName, self.name, "name")
        if self.failure_code is not None:
            self.failure_code = _coerce_enum(
                OrchestrationFailureCode, self.failure_code, "failure_code")
        motivo = _step_metadata_sensivel(self.metadata)
        if motivo:
            raise OrchestratorError(f"metadata sensível em step: {motivo}")

    def to_dict(self) -> dict:
        return {"schema": "nomos.council.orchestration_step.v1",
                "name": self.name.value, "ok": self.ok,
                "failure_code": self.failure_code.value if self.failure_code else None,
                "metadata": dict(self.metadata)}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)

    def __repr__(self) -> str:   # metadata-only, sem conteúdo bruto
        return (f"CouncilOrchestrationStep(name={self.name.value}, ok={self.ok}, "
                f"failure_code={self.failure_code}, "
                f"metadata_keys={sorted(self.metadata.keys())})")


# --------------------------- trace ---------------------------

@dataclass
class CouncilOrchestrationTrace:
    steps: list = field(default_factory=list)
    dry_run: bool = True
    private_mode: bool = False
    redacted: bool = True

    def __post_init__(self):
        # invariantes inegociáveis desta fase
        self.dry_run = True
        self.redacted = True

    def to_dict(self) -> dict:
        return {"schema": "nomos.council.orchestration_trace.v1",
                "dry_run": self.dry_run, "private_mode": self.private_mode,
                "redacted": self.redacted,
                "steps": [s.to_dict() if hasattr(s, "to_dict") else s for s in self.steps]}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)

    def __repr__(self) -> str:   # só nomes de etapa; nunca conteúdo
        nomes = [s.name.value if hasattr(s.name, "value") else s.name for s in self.steps]
        return (f"CouncilOrchestrationTrace(dry_run={self.dry_run}, "
                f"private_mode={self.private_mode}, redacted={self.redacted}, "
                f"steps={nomes})")


# --------------------------- resultado ---------------------------

@dataclass
class CouncilOrchestrationResult:
    session_id: str
    allowed: bool = False
    blocked: bool = True
    dry_run: bool = True
    would_execute: bool = False
    would_write_audit: bool = False
    failure_code: OrchestrationFailureCode | None = None
    final_envelope: dict = field(default_factory=dict)
    audit_result: dict = field(default_factory=dict)
    trace: dict = field(default_factory=dict)

    def __post_init__(self):
        # invariantes inegociáveis desta fase
        self.dry_run = True
        self.would_execute = False
        self.would_write_audit = False
        self.blocked = not self.allowed

    def to_dict(self) -> dict:
        return {"schema": "nomos.council.orchestration_result.v1",
                "session_id": self.session_id, "allowed": self.allowed,
                "blocked": self.blocked, "dry_run": self.dry_run,
                "would_execute": self.would_execute,
                "would_write_audit": self.would_write_audit,
                "failure_code": self.failure_code.value if self.failure_code else None,
                "final_envelope": self.final_envelope,
                "audit_result": self.audit_result, "trace": self.trace}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)

    def __repr__(self) -> str:   # nunca inclui final_envelope/audit_result/trace
        return (f"CouncilOrchestrationResult(session_id={self.session_id!r}, "
                f"allowed={self.allowed}, blocked={self.blocked}, dry_run={self.dry_run}, "
                f"would_execute={self.would_execute}, "
                f"would_write_audit={self.would_write_audit}, "
                f"failure_code={self.failure_code})")


# --------------------------- invariantes (defesa em profundidade) ---------------------------

def _verificar_persist_privado(private_mode: bool, final_envelope,
                               audit_result) -> CouncilOrchestrationFailure | None:
    """Em modo privado, NENHUM envelope pode declarar persist_allowed=true.

    Os objetos reais (`FinalResponseEnvelope`, `CouncilAuditEnvelope`) já forçam
    isso em construção — esta checagem é defesa em profundidade, e é exercitada
    diretamente por teste com objetos fabricados (não é alcançável via `.run()`
    normal, pois os modelos reais nunca permitem o estado inválido)."""
    if not private_mode:
        return None
    if getattr(final_envelope, "persist_allowed", False):   # pragma: no cover
        return CouncilOrchestrationFailure(
            OrchestrationFailureCode.ORCH_PRIVATE_MODE_PERSIST_DENIED,
            "final_envelope.persist_allowed=true em modo privado")
    for env in getattr(audit_result, "envelopes", None) or []:
        if getattr(env, "persist_allowed", False):          # pragma: no cover
            return CouncilOrchestrationFailure(
                OrchestrationFailureCode.ORCH_PRIVATE_MODE_PERSIST_DENIED,
                "audit envelope persist_allowed=true em modo privado")
    return None


def _verificar_dry_run_only(resultado: "CouncilOrchestrationResult"
                            ) -> CouncilOrchestrationFailure | None:
    """`dry_run`/`would_execute`/`would_write_audit` são travados por construção.

    Esta checagem é defesa em profundidade (inalcançável via `.run()` normal,
    pois `CouncilOrchestrationResult.__post_init__` já força os valores
    seguros) — exercitada diretamente por teste com um objeto fabricado."""
    if (getattr(resultado, "would_execute", False)
            or getattr(resultado, "would_write_audit", False)
            or not getattr(resultado, "dry_run", True)):     # pragma: no cover
        return CouncilOrchestrationFailure(
            OrchestrationFailureCode.ORCH_DRY_RUN_ONLY, "invariante dry-run violada")
    return None


# --------------------------- orquestrador ---------------------------

class CouncilOrchestratorDryRun:
    """Orquestrador DRY-RUN: compõe provider -> simulador -> gate -> audit envelope.

    Usa só componentes já dry-run do Council. Nunca chama motor/policy/audit/
    vault reais; nunca persiste; sem rede/subprocess/threading/asyncio; sem FS/
    env/tempo/random. Determinístico: mesma entrada -> mesma saída. Fail-closed:
    qualquer etapa (inclusive uma exceção de um componente plugável) resulta em
    `allowed=false`, mas o trace completo (metadata-only) é sempre produzido, na
    ordem exigida, com o Policy Gate sempre antes do envelope final e o audit
    envelope sempre depois do gate."""

    def __init__(self, *, provider: LocalCandidateProvider | None = None,
                 simulator: OfflineCouncilSimulator | None = None,
                 gate: CouncilPolicyGateDryRun | None = None,
                 audit_builder: CouncilAuditEnvelopeBuilder | None = None):
        self._provider = provider or DryRunAdapterCandidateProvider()
        self._simulator = simulator or OfflineCouncilSimulator()
        self._gate = gate or CouncilPolicyGateDryRun()
        self._builder = audit_builder or CouncilAuditEnvelopeBuilder()

    def run(self, entrada: CouncilOrchestrationInput) -> CouncilOrchestrationResult:
        steps: list[CouncilOrchestrationStep] = []
        raiz: CouncilOrchestrationFailure | None = None

        def _marcar_raiz(falha: CouncilOrchestrationFailure | None) -> None:
            nonlocal raiz
            if falha is not None and raiz is None:
                raiz = falha

        # 1. INPUT_VALIDATED — reconfirma invariantes mesmo após a construção
        #    (defesa em profundidade contra mutação pós-construção).
        entrada_ok = (bool(getattr(entrada, "session_id", "")) and
                     bool(getattr(entrada, "prompt", "")) and
                     isinstance(getattr(entrada, "max_candidates", 0), int) and
                     entrada.max_candidates >= 1)
        falha_entrada = (None if entrada_ok else CouncilOrchestrationFailure(
            OrchestrationFailureCode.ORCH_INPUT_INVALID,
            "entrada inválida (pós-construção)"))
        _marcar_raiz(falha_entrada)
        steps.append(CouncilOrchestrationStep(
            name=CouncilOrchestrationStepName.INPUT_VALIDATED, ok=entrada_ok,
            failure_code=(falha_entrada.code if falha_entrada else None),
            metadata={"mode": entrada.mode.value, "risk_level": entrada.risk_level.value,
                      "private_mode": bool(entrada.private_mode),
                      "contains_sensitive_data": bool(entrada.contains_sensitive_data),
                      "max_candidates": entrada.max_candidates, "local_only": True,
                      "prompt_chars": len(entrada.prompt or "")}))

        if not entrada_ok:
            # entrada inválida (ex.: atributo mutado após a construção) — pára
            # aqui, fail-closed: nenhuma etapa downstream pode confiar num
            # session_id/prompt/max_candidates que já se provaram inválidos.
            steps.append(CouncilOrchestrationStep(
                name=CouncilOrchestrationStepName.ORCHESTRATION_BLOCKED, ok=False,
                failure_code=falha_entrada.code,
                metadata={"failure_code": falha_entrada.code.value}))
            trace_invalida = CouncilOrchestrationTrace(
                steps=steps, private_mode=bool(getattr(entrada, "private_mode", False)))
            return CouncilOrchestrationResult(
                session_id=str(getattr(entrada, "session_id", "") or "session-invalido"),
                allowed=False, failure_code=falha_entrada.code,
                final_envelope={}, audit_result={}, trace=trace_invalida.to_dict())

        # 2. LOCAL_PROVIDER_EVALUATED
        request = LocalCandidateRequest(
            prompt=entrada.prompt, mode=entrada.mode, risk_level=entrada.risk_level,
            private_mode=entrada.private_mode,
            contains_sensitive_data=entrada.contains_sensitive_data,
            max_candidates=entrada.max_candidates)
        try:
            local_result = self._provider.generate(request)
            erro_provider = None
        except Exception as exc:                       # nunca deixa propagar
            local_result = LocalCandidateResult(candidates=[], failure_code=None)
            erro_provider = exc

        if erro_provider is not None:
            falha_provider = CouncilOrchestrationFailure(
                OrchestrationFailureCode.ORCH_PROVIDER_FAILED,
                f"exceção do provider: {type(erro_provider).__name__}")
        elif local_result.failure_code is CouncilFailureCode.NO_ELIGIBLE_LOCAL_ENGINE:
            falha_provider = CouncilOrchestrationFailure(
                OrchestrationFailureCode.ORCH_NO_CANDIDATES, "nenhum motor local elegível")
        elif local_result.failure_code is not None:
            # provider plugável pode devolver string em vez do enum: nunca
            # deixar um `.value` inexistente estourar para fora do run()
            _fc = local_result.failure_code
            falha_provider = CouncilOrchestrationFailure(
                OrchestrationFailureCode.ORCH_PROVIDER_FAILED,
                f"provider falhou: {getattr(_fc, 'value', str(_fc))}")
        elif not local_result.candidates:
            falha_provider = CouncilOrchestrationFailure(
                OrchestrationFailureCode.ORCH_NO_CANDIDATES,
                "provider não retornou candidatos")
        else:
            falha_provider = None
        _marcar_raiz(falha_provider)
        provider_ok = falha_provider is None
        try:
            n_engines = len(self._provider.list_engines())
        except Exception:
            n_engines = 0
        _fc_meta = local_result.failure_code
        steps.append(CouncilOrchestrationStep(
            name=CouncilOrchestrationStepName.LOCAL_PROVIDER_EVALUATED, ok=provider_ok,
            failure_code=(falha_provider.code if falha_provider else None),
            metadata={"engine_count": n_engines,
                      "candidate_count": len(local_result.candidates),
                      "council_failure_code": (getattr(_fc_meta, "value", str(_fc_meta))
                                               if _fc_meta is not None else None)}))

        # 3. CANDIDATES_CREATED (candidato malformado de provider plugável não
        # pode derrubar o run(): getattr com fallback; o simulador bloqueia
        # depois, fail-closed)
        candidatos = list(local_result.candidates)
        alias_por_candidato: dict[str, str] = {}
        engine_por_alias: dict[str, str] = {}
        for i, c in enumerate(candidatos):
            alias = _ALFABETO[i] if i < len(_ALFABETO) else f"C{i}"
            alias_por_candidato[getattr(c, "candidate_id", f"cand-{i}")] = alias
            engine_por_alias[alias] = getattr(c, "engine_id", "desconhecido")
        steps.append(CouncilOrchestrationStep(
            name=CouncilOrchestrationStepName.CANDIDATES_CREATED, ok=True,
            metadata={"candidate_count": len(candidatos)}))

        # 4. SIMULATOR_RAN — juízes fixos e determinísticos (um por candidato,
        #    nota máxima), nunca um "judge real com LLM".
        judge_fixtures = [
            SimulatedJudgeFixture(judge_engine_id=f"fixture:judge-{i}",
                                  candidate_alias=alias, overall=5)
            for i, alias in enumerate(sorted(alias_por_candidato.values()))]
        try:
            sim_result = self._simulator.run_with_candidates(
                candidates=candidatos, alias_por_candidato=alias_por_candidato,
                engine_por_alias=engine_por_alias, judge_fixtures=judge_fixtures,
                mode=entrada.mode, risk_level=entrada.risk_level, local_only=True,
                private_mode=entrada.private_mode,
                contains_sensitive_data=entrada.contains_sensitive_data,
                council_enabled=True, gate=None,
                provider_failure=local_result.failure_code,
                session_id=entrada.session_id)
            erro_sim = None
        except Exception as exc:
            sim_result = None
            erro_sim = exc
        falha_sim = (CouncilOrchestrationFailure(
            OrchestrationFailureCode.ORCH_SIMULATOR_FAILED,
            f"exceção do simulador: {type(erro_sim).__name__}")
            if erro_sim is not None else None)
        _marcar_raiz(falha_sim)
        steps.append(CouncilOrchestrationStep(
            name=CouncilOrchestrationStepName.SIMULATOR_RAN, ok=(falha_sim is None),
            failure_code=(falha_sim.code if falha_sim else None),
            metadata={
                "arbiter_blocked": (bool(sim_result.arbiter_decision.blocked)
                                   if sim_result else None),
                "review_count": (len(sim_result.reviews) if sim_result else 0),
                "council_failure_code": (sim_result.failure_code.value
                                         if sim_result and sim_result.failure_code
                                         else None)}))

        if sim_result is None:   # simulador plugável levantou exceção
            codigo = (raiz.code if raiz
                      else OrchestrationFailureCode.ORCH_SIMULATOR_FAILED)
            steps.append(CouncilOrchestrationStep(
                name=CouncilOrchestrationStepName.ORCHESTRATION_BLOCKED, ok=False,
                failure_code=codigo,
                metadata={"failure_code": codigo.value}))
            trace_falha = CouncilOrchestrationTrace(steps=steps,
                                                    private_mode=entrada.private_mode)
            return CouncilOrchestrationResult(
                session_id=entrada.session_id, allowed=False,
                failure_code=codigo,
                final_envelope={}, audit_result={}, trace=trace_falha.to_dict())

        # 5. POLICY_GATE_EVALUATED
        arb = sim_result.arbiter_decision
        gate_req = CouncilGateRequest(
            session_id=entrada.session_id, risk_level=sim_result.session.risk_level,
            mode=sim_result.session.mode, private_mode=sim_result.session.private_mode,
            contains_sensitive_data=entrada.contains_sensitive_data,
            requires_human_approval=False, arbiter_blocked=arb.blocked,
            final_content_chars=len(arb.final_content or ""),
            has_final_content=bool(arb.final_content) and not arb.blocked)
        try:
            gate_decisao = self._gate.evaluate(gate_req)
            erro_gate = None
        except Exception as exc:
            gate_decisao = None
            erro_gate = exc
        if erro_gate is not None:
            falha_gate = CouncilOrchestrationFailure(
                OrchestrationFailureCode.ORCH_INTERNAL_INVARIANT_FAILED,
                f"exceção do gate: {type(erro_gate).__name__}")
            gate_decisao = CouncilGateDecision(allowed=False, failure_code=None)
        elif not gate_decisao.allowed:
            falha_gate = CouncilOrchestrationFailure(
                OrchestrationFailureCode.ORCH_POLICY_GATE_DENIED,
                f"gate negou: {gate_decisao.failure_code}")
        else:
            falha_gate = None
        _marcar_raiz(falha_gate)
        steps.append(CouncilOrchestrationStep(
            name=CouncilOrchestrationStepName.POLICY_GATE_EVALUATED,
            ok=gate_decisao.allowed,
            failure_code=(falha_gate.code if falha_gate else None),
            metadata={"gate_allowed": gate_decisao.allowed,
                      "gate_failure_code": (gate_decisao.failure_code.value
                                            if gate_decisao.failure_code else None)}))

        # 6. FINAL_ENVELOPE_CREATED — sempre depois do gate, nunca antes.
        conteudo = arb.final_content if gate_decisao.allowed else None
        final_envelope = FinalResponseEnvelope(
            session_id=entrada.session_id, gate_decision=gate_decisao.to_dict(),
            allowed=gate_decisao.allowed, content=conteudo,
            persist_allowed=not entrada.private_mode)
        steps.append(CouncilOrchestrationStep(
            name=CouncilOrchestrationStepName.FINAL_ENVELOPE_CREATED, ok=True,
            metadata={"allowed": final_envelope.allowed, "blocked": final_envelope.blocked,
                      "persist_allowed": final_envelope.persist_allowed}))

        # 7. AUDIT_ENVELOPE_CREATED — sempre depois do envelope final/gate.
        try:
            audit_result = self._builder.build_for_result(
                sim_result, entrada.private_mode)
            erro_audit = None
        except Exception as exc:
            audit_result = None
            erro_audit = exc
        if erro_audit is not None:
            falha_audit = CouncilOrchestrationFailure(
                OrchestrationFailureCode.ORCH_INTERNAL_INVARIANT_FAILED,
                f"exceção do audit envelope: {type(erro_audit).__name__}")
            audit_result = CouncilAuditDryRunResult(allowed=False, envelopes=[])
        elif not audit_result.allowed:
            falha_audit = CouncilOrchestrationFailure(
                OrchestrationFailureCode.ORCH_AUDIT_ENVELOPE_DENIED,
                f"audit envelope negou: {audit_result.failure_code}")
        else:
            falha_audit = None
        _marcar_raiz(falha_audit)
        steps.append(CouncilOrchestrationStep(
            name=CouncilOrchestrationStepName.AUDIT_ENVELOPE_CREATED,
            ok=audit_result.allowed,
            failure_code=(falha_audit.code if falha_audit else None),
            metadata={"envelope_count": len(audit_result.envelopes),
                      "audit_failure_code": (audit_result.failure_code.value
                                             if audit_result.failure_code else None)}))

        # defesa em profundidade: modo privado nunca pode persistir em nenhum envelope
        falha_privada = _verificar_persist_privado(
            entrada.private_mode, final_envelope, audit_result)
        _marcar_raiz(falha_privada)

        permitido = (provider_ok and gate_decisao.allowed and audit_result.allowed
                    and falha_privada is None)
        nome_final = (CouncilOrchestrationStepName.ORCHESTRATION_COMPLETED if permitido
                     else CouncilOrchestrationStepName.ORCHESTRATION_BLOCKED)
        steps.append(CouncilOrchestrationStep(
            name=nome_final, ok=permitido,
            failure_code=(raiz.code if (raiz and not permitido) else None),
            metadata={"failure_code": (raiz.code.value if (raiz and not permitido)
                                       else None)}))

        trace = CouncilOrchestrationTrace(steps=steps, private_mode=entrada.private_mode)
        resultado = CouncilOrchestrationResult(
            session_id=entrada.session_id, allowed=permitido,
            failure_code=(raiz.code if not permitido else None),
            final_envelope=final_envelope.to_dict(), audit_result=audit_result.to_dict(),
            trace=trace.to_dict())

        # defesa em profundidade final: dry_run/would_execute/would_write_audit
        falha_dry = _verificar_dry_run_only(resultado)
        if falha_dry is not None:   # pragma: no cover - inalcançável por construção
            resultado = CouncilOrchestrationResult(
                session_id=resultado.session_id, allowed=False,
                failure_code=OrchestrationFailureCode.ORCH_DRY_RUN_ONLY,
                final_envelope=resultado.final_envelope,
                audit_result=resultado.audit_result, trace=resultado.trace)
        return resultado
