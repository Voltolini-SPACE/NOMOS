# ARBITRAGEM — SPEC (implementation-loop-100)

**Data:** 2026-07-05 · **Branch:** main

## Validação do que existe
- `cognition/engine_router.py`: **roteamento** — escolhe 1 melhor motor. (existe)
- `council/*`: **modelo e contrato de arbitragem** (AnswerCandidate → BlindReview →
  JudgeScore → ArbiterDecision → DisagreementReport) porém **dry-run/simulado**;
  `local_harness.REAL_LOCAL_ENGINE_EXECUTION_ENABLED = False`. (existe, mas não executa)
- **Falta:** orquestração REAL onde vários motores prontos geram candidatos, debatem
  e convergem na melhor execução — sem supor/mentir/inventar.

## Objetivo
Construir `cognition/arbitragem.py`: arbitragem REAL, local-first, fail-closed e honesta.
Reusa os modelos puros do `council` (já testados). Não altera o gate dry-run do council.

## Contrato
- `EngineRunner` (Protocol): `engine_id`, `local: bool`, `available() -> bool`,
  `run(prompt, system="") -> str` (execução real; levanta em falha).
- `arbitrar(tarefa, runners, *, rounds, min_candidatos, allow_cloud, max_retries) -> ArbitrationOutcome`.

## Fluxo (tudo real)
1. Selecionar: só runners `available()`; cloud só se `allow_cloud` (opt-in). Local-first.
2. Candidatos (rodada 1): cada runner `run()` de verdade → AnswerCandidate.
   Falha/vazio → candidate com `failure_code` (sem content inventado).
3. Debate (rodadas ≥1): juiz cego pontua os candidatos dos OUTROS; motores podem revisar
   (re-execução real) até estabilizar ou atingir `rounds`.
4. Arbitrar: agrega JudgeScore → ArbiterDecision; calcula `score_spread` → DisagreementReport.

## Invariantes de honestidade (fail-closed, testadas)
- 0 motor pronto ⇒ `blocked`, `NO_ELIGIBLE_LOCAL_ENGINE`, **sem content**.
- Todos falham ⇒ `blocked`, `INSUFFICIENT_JUDGES`/`ARBITER_UNSAFE_OUTPUT`, sem content.
- `final_content`, se houver, **é idêntico ao de um candidato real** (nunca sintetizado).
- Desacordo HIGH ⇒ `requires_clarification`/`requires_human_approval` (nunca finge certeza).
- Cloud nunca entra sem opt-in explícito.
- "Esforço máximo": tenta todos os prontos, retries limitados, múltiplas rodadas.

## Fora de escopo / proibido
- Não flipar `REAL_LOCAL_ENGINE_EXECUTION_ENABLED` do council.
- Não rede/secret/deploy. Não tocar `.github/`, `pyproject.toml`, `setup.cfg`.
- Não inventar saída de motor. Core stdlib-only, I/O só nos runners.

## Testes
- Runners determinísticos (test doubles) provam debate/convergência.
- Sandbox sem motor real: arbitragem retorna `no_engine` honesto (evidência).
- Invariantes acima, cada uma com teste. ruff + pytest -q anti-regressão.
