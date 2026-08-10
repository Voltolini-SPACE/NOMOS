# ETAPA 0 — REBASELINE · ABSORPTION-04

```
DATE_TIME=2026-08-10T11:51:56Z
HOST=PanheonAI.local

MAIN_HEAD=2cea197eb188121fcd507b53f02935b5edf435ad
ORIGIN_MAIN=2cea197eb188121fcd507b53f02935b5edf435ad     (git fetch; SEM drift)
ABSORPTION_03_HEAD=d6ec5d9f2164d72f775dc75b3142fc4ffe0ac1c2
MISSION_BRANCH=feat/nomos-absorption-04  (nasce de d6ec5d9)
ANCESTRY_VALID=TRUE

DIRTY_STATE=2   (untracked: docs/architecture/NOMOS_MOSAIC_NAMING_*.md)
ACTIVE_WRITERS=10 processos `claude --output-format`; nenhum terceiro com
                arquivo aberto no repo (só a própria sessão)

GUARD_SHA=2ecc5ff7051603675ccdf7ba087340759c246f26148a99b7db3be95628317ecc
FULL_TEST_BASELINE=2292 passed / 14 skipped / 0 failed · ruff limpo

HERMES_PID=1336   HERMES_PORT=9119
OPENCLAW_PID=996  OPENCLAW_PORT=18789
OLLAMA_PID=60676  OLLAMA_PORT=11434
WHATSAPP_ENABLED=False
NOMOS_LAUNCHAGENTS=0
```

## Validação
```
BASELINE_CURRENT=TRUE
TARGET_LOCKED=FALSE
GUARDS_INTACT=TRUE
PRODUCTION_UNTOUCHED=TRUE
ABSORPTION_03_ANCESTRY_VALID=TRUE
```
Nenhuma STOP condition disparou.

## Decisão registrada: por que um parser de cron próprio
Antes de escrever, verifiquei o ambiente:
```
croniter        ausente
cron_converter  ausente
crontab         ausente
apscheduler     ausente
zoneinfo        DISPONÍVEL (stdlib, com tzdata do SO)
```
A missão manda não escrever parser simplificado *se uma implementação robusta
estiver disponível*. Nenhuma está. E o NOMOS declara DUAS dependências no total
(`cryptography`, `argon2-cffi`) — puxar uma terceira para uma gramática de 5
campos, num projeto cuja premissa é superfície mínima auditável, seria o trade
errado. Então: parser **completo**, com a semântica OR do POSIX, não simplificado.
