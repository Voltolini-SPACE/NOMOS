# ETAPA 0 — REBASELINE · NOMOS-HERMES-OPENCLAW-ABSORPTION-02

Capturado ANTES de qualquer escrita. Reprodutível pelos comandos indicados.

```
DATE_TIME=2026-08-10T10:27:25Z
HOST=PanheonAI.local
NOMOS_REPO=/Users/AI/Desktop/NOMOS_REPO/nomos
MAIN_HEAD=2cea197eb188121fcd507b53f02935b5edf435ad
ORIGIN_MAIN=2cea197eb188121fcd507b53f02935b5edf435ad     (git fetch feito; SEM drift)
MISSION_BRANCH=feat/nomos-absorption-02
MISSION_BASE=fb68220cd290eccc692d6714f8de9a7d84b0cb5d    (ponta da ABSORPTION-01)
DIRTY_STATE=2  (apenas untracked: docs/architecture/NOMOS_MOSAIC_NAMING_*.md)
ACTIVE_WRITERS=10 processos `claude --output-format`, cwd /Users/AI/Desktop
HERMES_PID=1336   HERMES_PORT=9119
OPENCLAW_PID=996  OPENCLAW_PORT=18789
GUARD_SHA=2ecc5ff7051603675ccdf7ba087340759c246f26148a99b7db3be95628317ecc
NOMOS_TEST_BASELINE=2153 passed / 14 skipped / 0 failed · ruff limpo
```

## Worktrees no instante da captura
```
~/Desktop/NOMOS_REPO/nomos                                    2cea197 [main]
~/Projects/nomos-hermes-architecture/nomos-fix-wt             6c049c7 [fix/test-home-isolation-mc]
~/Projects/nomos-hermes-capability-gap/workspace/nomos-nh-wt  13113f3 [feat/nh-capability-gap-01]
~/Projects/nomos-hermes-capability-gap/workspace/nomos-num-wt 544ddee [fix/numeros-superficies]
~/Projects/nomos-runtime-absorption/wt                        fb68220 [feat/nomos-runtime-absorption-01]
```

## Gate
```
BASELINE_CURRENT=TRUE        (main == origin/main; nenhum drift desde a 01)
TARGET_LOCKED=FALSE          (10 sessões vivas, NENHUMA com arquivo aberto no repo)
GUARDS_INTACT=TRUE
PRODUCTION_UNTOUCHED=TRUE
```

## Decisão de base
A worktree da 02 nasce de **`fb68220`** (ponta da ABSORPTION-01), não de `main`.
Motivo: a FASE 1 da 02 age exatamente sobre as duas rotas boundary-only que a 01
deixou documentadas, e o PDP/PEP da 01 são pré-requisito. `fb68220` é descendente
de `2cea197e` (verificado com `git merge-base --is-ancestor`), então nada de
`main` foi ignorado.

## Mudança relevante de ambiente desde a 01
`MODELS_LOCAL` foi **remontado** e o Ollama voltou (`:11434`, 11 modelos:
qwen2.5-7b-ptctx, llama3.1:8b, gemma3:12b, nomic-embed-text, …). Isso destravou a
FASE 5 (motor real), que na 01 estava bloqueada por infraestrutura.
