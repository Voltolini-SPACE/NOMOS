"""NOMOS cognition.arbitragem — arbitragem REAL entre motores (além do roteamento).

O roteador escolhe UM motor. A arbitragem vai além: seleciona os motores PRONTOS
para a tarefa, faz cada um produzir um candidato REAL, os candidatos são revisados
às cegas por juízes, os motores podem revisar suas respostas com base nas críticas
(debate em rodadas) e um árbitro converge na melhor execução real.

Princípios inegociáveis (fail-closed, honesto — nunca supor/mentir/inventar):
- Só entra no debate motor que está de fato PRONTO (`available()`), executado de verdade.
- Conteúdo de um candidato só existe se o motor realmente o produziu; falha vira
  `failure_code` (sem conteúdo fabricado).
- `final_content`, quando houver, é IDÊNTICO ao de um candidato real — nunca sintetizado.
- Sem motor pronto ⇒ bloqueia e diz por quê. Nunca devolve resposta inventada.
- Desacordo alto ⇒ exige clarificação/aprovação humana; jamais finge certeza.
- Nuvem só participa com opt-in explícito (local-first).
- Esforço máximo: tenta todos os motores prontos, com retries limitados e rodadas de debate.

Núcleo stdlib-only e sem I/O: todo I/O de rede/modelo vive nos `EngineRunner` reais.
Reutiliza os modelos puros e já testados de `nomos.council.models`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Protocol, runtime_checkable

from nomos.council.models import (
    AnswerCandidate,
    ArbiterDecision,
    CouncilConfidence,
    CouncilDisagreementLevel,
    CouncilFailureCode,
    DisagreementReport,
    JudgeScore,
)

# ----------------------------------------------------------------------------
# Contrato de motor executável (real). Os runners de produção embrulham
# OllamaProvider / AnthropicProvider / EmbeddedProvider; nos testes, dublês
# determinísticos os substituem — mas em ambos os casos o conteúdo vem do run().
# ----------------------------------------------------------------------------
@runtime_checkable
class EngineRunner(Protocol):
    engine_id: str
    local: bool

    def available(self) -> bool: ...

    def run(self, prompt: str, *, system: str = "") -> str: ...


# Padrões que jamais devem sair como resposta (segurança/privacidade) — sinais REAIS.
_PERIGO = [
    re.compile(r"rm\s+-rf\s+/"),
    re.compile(r":\(\)\s*\{"),                    # fork bomb
    re.compile("s" + r"k-[A-Za-z0-9]{16,}"),      # chave estilo OpenAI
    re.compile("g" + r"hp_[A-Za-z0-9]{16,}"),     # GitHub PAT
    re.compile("-----" + r"BEGIN [A-Z ]*PRIVATE"),
]
_HEDGE = ("não sei", "nao sei", "talvez", "acho que", "provavelmente", "não tenho certeza")


@dataclass
class ArbitrationOutcome:
    """Resultado da arbitragem — seguro para auditoria (sem vazar conteúdo em repr)."""
    status: str                                   # "ok" | "blocked" | "no_engine"
    decision: ArbiterDecision
    disagreement: DisagreementReport
    candidates: list = field(default_factory=list, repr=False)
    scores: dict = field(default_factory=dict, repr=False)     # alias -> JudgeScore
    engines_ready: list = field(default_factory=list)
    engines_tried: list = field(default_factory=list)          # log de esforço real
    rounds_run: int = 0
    failure_code: CouncilFailureCode | None = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "blocked": self.decision.blocked,
            "confidence": self.decision.confidence.value,
            "selected": self.decision.selected_candidate_alias,
            "final_len": len(self.decision.final_content),
            "disagreement": self.disagreement.level.value,
            "requires_clarification": self.disagreement.requires_clarification,
            "engines_ready": list(self.engines_ready),
            "engines_tried": list(self.engines_tried),
            "rounds_run": self.rounds_run,
            "failure_code": self.failure_code.value if self.failure_code else None,
            "reasons": list(self.decision.reasons),
        }


# ----------------------------------------------------------------------------
# Juiz determinístico e transparente. Não "inventa qualidade": pontua por sinais
# mensuráveis — consenso entre motores (acordo), estrutura, segurança, privacidade.
# ----------------------------------------------------------------------------
def _tokens(texto: str) -> set:
    return set(re.findall(r"\w+", texto.lower()))


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _consenso(idx: int, textos: list[str]) -> float:
    """Acordo médio do candidato idx com os demais (0..1) — base da 'discussão'."""
    outros = [t for j, t in enumerate(textos) if j != idx]
    if not outros:
        return 0.5
    meu = _tokens(textos[idx])
    return sum(_jaccard(meu, _tokens(o)) for o in outros) / len(outros)


def _clamp5(x: float) -> int:
    return max(0, min(5, int(round(x))))


def julgar_heuristico(candidato: AnswerCandidate, todos: list[str], idx: int,
                      *, local: bool) -> JudgeScore:
    """Pontua um candidato com sinais reais e determinísticos (0–5 por critério)."""
    txt = candidato.content
    perigoso = any(p.search(txt) for p in _PERIGO)
    tem_segredo = any(p.search(txt) for p in _PERIGO[2:])
    hedge = any(h in txt.lower() for h in _HEDGE)
    consenso = _consenso(idx, todos)                       # 0..1
    n = len(txt.strip())

    correctness = _clamp5(1 + consenso * 4)                # acordo entre motores
    clarity = _clamp5(5 if 20 <= n <= 4000 else (2 if n else 0))
    safety = 0 if perigoso else 5
    privacy = 0 if tem_segredo else 5
    usefulness = _clamp5(0 if n == 0 else 2 + consenso * 3)
    evidence = _clamp5(1 + min(4, len(re.findall(r"\d+|https?://", txt))))
    # risco de alucinação: alto quando destoa do consenso E afirma com firmeza (sem hedge)
    hallucination = _clamp5((1 - consenso) * 5 * (0.5 if hedge else 1.0))

    return JudgeScore(
        candidate_alias=candidato.candidate_id,
        correctness=correctness, clarity=clarity, safety=safety, privacy=privacy,
        usefulness=usefulness, evidence=evidence, hallucination_risk=hallucination,
        followed_local_first=local,
        requires_human_approval=bool(perigoso or tem_segredo),
        contains_sensitive_data=bool(tem_segredo),
    )


_QUALIDADE = ("correctness", "clarity", "safety", "privacy", "usefulness", "evidence")


def _agregado(s: JudgeScore) -> float:
    base = sum(getattr(s, c) for c in _QUALIDADE) / len(_QUALIDADE)
    return base - 0.6 * s.hallucination_risk       # penaliza risco de alucinação


# ----------------------------------------------------------------------------
# Orquestrador da arbitragem
# ----------------------------------------------------------------------------
def _gerar_candidato(runner: EngineRunner, prompt: str, system: str,
                     max_retries: int, tried: list) -> AnswerCandidate:
    """Executa o motor DE VERDADE. Falha/vazio ⇒ failure_code (sem inventar)."""
    ultimo_erro = None
    for tentativa in range(max_retries + 1):
        tried.append(f"{runner.engine_id}#run{tentativa + 1}")
        try:
            texto = runner.run(prompt, system=system)
        except Exception as exc:                    # motor real pode falhar
            ultimo_erro = str(exc)
            continue
        if texto and texto.strip():
            return AnswerCandidate(
                candidate_id=f"cand-{runner.engine_id}",
                engine_id=runner.engine_id,
                content=texto,
                metadata={"local": runner.local},
            )
        ultimo_erro = "resposta vazia"
    return AnswerCandidate(
        candidate_id=f"cand-{runner.engine_id}",
        engine_id=runner.engine_id,
        content="",
        failure_code=CouncilFailureCode.ENGINE_FAILED,
        metadata={"erro": ultimo_erro or "desconhecido", "local": runner.local},
    )


def arbitrar(prompt: str, runners: list[EngineRunner], *,
             system: str = "", rounds: int = 2, min_candidatos: int = 2,
             allow_cloud: bool = False, max_retries: int = 1,
             judge: Callable | None = None) -> ArbitrationOutcome:
    """Arbitragem real entre motores. Ver docstring do módulo para as invariantes.

    - `rounds`: nº de rodadas de debate (≥1). Após a 1ª, motores podem revisar.
    - `min_candidatos`: mínimo de candidatos com conteúdo para o árbitro decidir.
    - `allow_cloud`: se False, motores não-locais são excluídos (local-first).
    - `judge`: função de pontuação (default: heurística determinística por consenso).
    """
    judge = judge or julgar_heuristico
    rounds = max(1, rounds)
    tried: list[str] = []

    # 1) Seleção — só o que está PRONTO; nuvem só com opt-in. Local primeiro.
    prontos: list[EngineRunner] = []
    for r in runners:
        tried.append(f"{r.engine_id}#available")
        try:
            ok = r.available()
        except Exception:
            ok = False
        if not ok:
            continue
        if not r.local and not allow_cloud:
            continue
        prontos.append(r)
    prontos.sort(key=lambda r: (0 if r.local else 1, r.engine_id))
    ready_ids = [r.engine_id for r in prontos]

    def _bloqueio(fc: CouncilFailureCode, motivo: str, status: str = "blocked",
                  rounds_run: int = 0) -> ArbitrationOutcome:
        return ArbitrationOutcome(
            status=status,
            decision=ArbiterDecision(decision_id="arb", blocked=True,
                                     confidence=CouncilConfidence.LOW,
                                     reasons=[motivo]),
            disagreement=DisagreementReport(level=CouncilDisagreementLevel.LOW),
            engines_ready=ready_ids, engines_tried=tried,
            rounds_run=rounds_run, failure_code=fc,
        )

    if not prontos:
        return _bloqueio(CouncilFailureCode.NO_ELIGIBLE_LOCAL_ENGINE,
                         "nenhum motor pronto para a tarefa", status="no_engine")

    # 2) Candidatos reais (rodada 1)
    candidatos = [_gerar_candidato(r, prompt, system, max_retries, tried) for r in prontos]

    rounds_run = 1
    scores: dict = {}
    # 3) Debate — rodadas de crítica cega + possível revisão real
    for _ in range(rounds):
        vivos = [c for c in candidatos if c.content and c.failure_code is None]
        if len(vivos) < min_candidatos and not (rounds_run < rounds):
            break
        textos = [c.content for c in vivos]
        scores = {
            c.candidate_id: judge(c, textos, i, local=bool(c.metadata.get("local", True)))
            for i, c in enumerate(vivos)
        }
        if rounds_run >= rounds or len(vivos) < 2:
            break
        # revisão: cada motor vê os candidatos anônimos dos OUTROS e pode revisar
        mudou = False
        for i, r in enumerate(prontos):
            cand = candidatos[i]
            if cand.failure_code is not None:
                continue
            criticas = "\n---\n".join(
                c.anonymized(alias=f"resposta_{j}").content
                for j, c in enumerate(vivos) if c.candidate_id != cand.candidate_id)
            if not criticas:
                continue
            prompt_rev = (
                f"{prompt}\n\n[debate] Outras respostas anônimas para a mesma tarefa:\n"
                f"{criticas}\n\nRevise e melhore a SUA resposta se for o caso. "
                f"Se a sua já for a melhor, repita-a.")
            novo = _gerar_candidato(r, prompt_rev, system, max_retries, tried)
            if novo.failure_code is None and novo.content.strip() != cand.content.strip():
                candidatos[i] = novo
                mudou = True
        rounds_run += 1
        if not mudou:
            break

    # 4) Arbitrar
    vivos = [c for c in candidatos if c.content and c.failure_code is None]
    if len(vivos) < min_candidatos and len(vivos) == 0:
        return _bloqueio(CouncilFailureCode.INSUFFICIENT_JUDGES,
                         "nenhum candidato com conteúdo real", rounds_run=rounds_run)

    textos = [c.content for c in vivos]
    scores = {c.candidate_id: judge(c, textos, i, local=bool(c.metadata.get("local", True)))
              for i, c in enumerate(vivos)}

    agregados = {cid: _agregado(s) for cid, s in scores.items()}
    melhor_id = max(agregados, key=agregados.get)
    melhor_cand = next(c for c in vivos if c.candidate_id == melhor_id)
    melhor_score = scores[melhor_id]

    # segurança/privacidade: nunca liberar saída perigosa
    if melhor_score.safety < 3 or melhor_score.privacy < 3:
        return _bloqueio(CouncilFailureCode.ARBITER_UNSAFE_OUTPUT,
                         "melhor candidato reprovou em segurança/privacidade",
                         rounds_run=rounds_run)

    spread = (max(agregados.values()) - min(agregados.values())) if len(agregados) > 1 else 0.0
    if spread >= 2.5:
        nivel = CouncilDisagreementLevel.HIGH
    elif spread >= 1.2:
        nivel = CouncilDisagreementLevel.MEDIUM
    else:
        nivel = CouncilDisagreementLevel.LOW
    desacordo = DisagreementReport(
        level=nivel, score_spread=round(spread, 3),
        reasons=[f"spread={round(spread, 3)} entre {len(agregados)} candidatos"])

    if nivel is CouncilDisagreementLevel.HIGH:
        confianca = CouncilConfidence.LOW
    elif nivel is CouncilDisagreementLevel.MEDIUM:
        confianca = CouncilConfidence.MEDIUM
    else:
        confianca = CouncilConfidence.HIGH

    decisao = ArbiterDecision(
        decision_id="arb",
        selected_candidate_alias=melhor_id,
        final_content=melhor_cand.content,      # IDÊNTICO ao candidato real
        confidence=confianca,
        requires_policy_gate=True,
        blocked=False,
        reasons=[
            f"vencedor={melhor_cand.engine_id}",
            f"agregado={round(agregados[melhor_id], 3)}",
            f"consenso/segurança verificados; {len(vivos)} candidatos reais",
        ],
    )
    return ArbitrationOutcome(
        status="ok", decision=decisao, disagreement=desacordo,
        candidates=candidatos, scores=scores,
        engines_ready=ready_ids, engines_tried=tried, rounds_run=rounds_run,
    )


# ----------------------------------------------------------------------------
# Runners de produção — embrulham os provedores reais do NOMOS. Cada um só
# reporta `available()=True` quando o motor está DE FATO pronto.
# ----------------------------------------------------------------------------
@dataclass
class OllamaRunner:
    """Motor de texto local via Ollama (real)."""
    engine_id: str = "ollama"
    local: bool = True
    _provider: object | None = None

    def _prov(self):
        if self._provider is None:
            from nomos.cognition.providers import OllamaProvider
            self._provider = OllamaProvider()
        return self._provider

    def available(self) -> bool:
        try:
            return bool(self._prov().available())
        except Exception:
            return False

    def run(self, prompt: str, *, system: str = "") -> str:
        msgs = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
        return self._prov().chat(msgs).text


@dataclass
class EmbeddedRunner:
    """Cérebro leve embutido (real). Local por definição."""
    home: object
    engine_id: str = "embutido"
    local: bool = True
    _provider: object | None = None

    def _prov(self):
        if self._provider is None:
            from nomos.cognition.embutido import EmbeddedProvider
            self._provider = EmbeddedProvider(self.home)
        return self._provider

    def available(self) -> bool:
        try:
            return bool(self._prov().disponivel())
        except Exception:
            return False

    def run(self, prompt: str, *, system: str = "") -> str:
        prov = self._prov()
        # EmbeddedProvider expõe geração via chat/responder conforme a versão;
        # tentamos os nomes conhecidos sem inventar retorno.
        for nome in ("chat", "responder", "gerar", "complete"):
            fn = getattr(prov, nome, None)
            if callable(fn):
                out = fn([{"role": "user", "content": prompt}]) if nome == "chat" else fn(prompt)
                return getattr(out, "text", out) if not isinstance(out, str) else out
        raise RuntimeError("EmbeddedProvider sem método de geração conhecido")


def montar_runners_producao(home) -> list[EngineRunner]:
    """Monta os motores REAIS locais para arbitragem (cérebro embutido + Ollama).

    Cada runner só participa se `available()` for True de fato. Nuvem não entra
    aqui: é opt-in explícito via ``montar_runner_nuvem`` (gates A2+A3 + cofre).
    """
    return [EmbeddedRunner(home=home), OllamaRunner()]


# ----------------------------------------------------------------------------
# Nuvem opt-in (MC29): o runner de nuvem SÓ NASCE depois de todos os gates.
# Mesmo trilho do Router._try_cloud: cadeado -> A2 egress -> A3 credencial ->
# cofre. Qualquer etapa negada => (None, motivo) — fail-closed, sem exceção
# silenciosa. `arbitrar` continua excluindo não-locais sem allow_cloud=True.
# ----------------------------------------------------------------------------
CLOUD_KEY_NAME = "anthropic_api_key"
CLOUD_TARGET = "api.anthropic.com"


class CloudRunner:
    """Runner de NUVEM já autorizado. Recebe a chave após os gates; nunca a
    expõe em repr/log; `local=False` garante exclusão sem opt-in."""

    engine_id = "claude"
    local = False

    def __init__(self, api_key: str, factory=None):
        self._api_key = api_key
        self._factory = factory

    def __repr__(self) -> str:  # chave jamais aparece
        return "CloudRunner(engine_id='claude')"

    def available(self) -> bool:
        return bool(self._api_key)

    def run(self, prompt: str, *, system: str = "") -> str:
        factory = self._factory
        if factory is None:
            from nomos.cognition.providers import AnthropicProvider
            factory = AnthropicProvider
        msgs = ([{"role": "system", "content": system}] if system else [])
        msgs.append({"role": "user", "content": prompt})
        return factory(api_key=self._api_key).chat(msgs).text


def montar_runner_nuvem(home, *, policy, vault, approver,
                        passphrase: str | None,
                        gate=None, factory=None):
    """Constrói o runner de nuvem SOMENTE se todas as barreiras passarem.

    Ordem (cada uma fail-closed): 1) cadeado de localidade desligado;
    2) gate A2 (egress) aprovado; 3) gate A3 (credencial) aprovado;
    4) passphrase fornecida e chave presente no cofre.
    Devolve ``(runner, "")`` ou ``(None, motivo)``.
    """
    from nomos.kernel import localidade
    from nomos.kernel.policy import Category
    from nomos.kernel.policy import gate as gate_padrao
    g = gate or gate_padrao

    if localidade.esta_ligado(home):
        return None, ("cadeado só-local LIGADO — nuvem não participa "
                      "(decisão consciente: nomos local off)")
    d_net = policy.decide(Category.NET_EGRESS, target=CLOUD_TARGET)
    if not g(d_net, approver):
        return None, "egress negado no gate A2 (sem aprovação)"
    d_cred = policy.decide(Category.CRED_USE, target=f"vault:{CLOUD_KEY_NAME}")
    if not g(d_cred, approver):
        return None, "uso de credencial negado no gate A3"
    if not passphrase:
        return None, "passphrase do cofre não fornecida"
    try:
        key = vault.get(CLOUD_KEY_NAME, passphrase)
    except Exception as exc:
        return None, f"chave '{CLOUD_KEY_NAME}' indisponível no cofre: {exc}"
    return CloudRunner(api_key=key, factory=factory), ""
