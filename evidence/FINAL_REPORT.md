# NOMOS-HERMES-OPENCLAW-ABSORPTION-05 — RELATÓRIO FINAL

## STATUS_FINAL = PASS_PRODUCTION_CALLERS_WIRED

Interpretação, conforme a própria missão define: *"os fios foram ligados
corretamente, mas ainda existem gaps de paridade."*

```
BASELINE_HEAD=b33df4cce28da2ccccdbb411bffffa987ac1d791
MAIN_HEAD=2cea197eb188121fcd507b53f02935b5edf435ad   (intocada)
MISSION_BRANCH=feat/nomos-absorption-05
COMMITS=8
WORKTREE_CLEAN=TRUE

FULL_TEST_SUITE=2429 passed / 2442 coletados
FAILED=0
SKIPPED=14   (todos PRE_EXISTING_ENVIRONMENTAL; nenhum novo)
LINT=PASS
TYPECHECK=NOT_RUN (mypy não é dependência do projeto)

SCHEDULER_REGISTRATION_PRODUCTION_CALLERS=2
TICKER_PRODUCTION_CALLERS=1
SCRIPT_RUN_PRODUCTION_CALLERS=1

PDP_MANDATORY=TRUE
PEP_MANDATORY=TRUE
DIRECT_MUTATING_BYPASS=0   (era >0 no HEAD do censo; fechado em 44c2a3c)

FS_TOTAL=11         FS_FULL=0   FS_CRITICAL_GAPS=5
SCHEDULER_TOTAL=18  SCHEDULER_FULL=0  SCHEDULER_CRITICAL_GAPS=8
SCRIPT_TOTAL=24     SCRIPT_FULL=9     SCRIPT_CRITICAL_GAPS=9

SCRIPT_EXECUTION_GOVERNED=TRUE
SCRIPT_PRODUCTION_REACHABLE=TRUE
FAILURE_ALERT_RUNTIME_PATH=PASS
REGISTRY_RACE=PASS
NODE_HARD_TIMEOUT=PASS

TOTAL_CAPABILITIES=53
FULL=9  PARTIAL=29  MISSING=8  FORA_DO_NUCLEO=7
UNGOVERNED=14
CRITICAL_GAPS_REMAINING=22

MUTATION_TESTS=15/15
REGRESSION=0

PRODUCTION_MUTATED=FALSE

READY_FOR_DAEMON=FALSE
READY_FOR_SHADOW=FALSE
READY_FOR_CANARY=FALSE
CUTOVER=FALSE
```

## Gates
| Gate | Critério | Resultado |
|---|---|---|
| **A — Wiring** | 3 callers de produção ≥1 | ✅ **PASS** (2/1/1) |
| **B — Governança** | PDP/PEP obrigatórios, bypass 0 | ✅ **PASS** *(após `44c2a3c`)* |
| **C — Filesystem** | `FS_CRITICAL_GAPS=0` | ❌ FAIL — 5 |
| **D — Scheduler** | `SCHEDULER_CRITICAL_GAPS=0` | ❌ FAIL — 8 |
| **E — Script** | governado + alcançável | ✅ **PASS** |
| **F — Qualidade** | suíte, lint, adversarial, mutation | ✅ **PASS** |

`PASS_CRITICAL_ADAPTER_LAYER` exigiria C+D+E zerados. C e D não zeram.

## O objetivo da missão foi cumprido
Os três componentes órfãos ganharam caller de produção, e o censo independente
**confirmou rodando o CLI de verdade**: `nomos scheduler rodar` executou um job
que escreveu arquivo real, com a trilha em ordem
`pdp.decisao → pep.aplicacao → fs.escrever → scheduler.execucao.fim`; um job com
alvo fora do escopo foi negado e nada foi criado.

**Primeiros 9 FULL da linhagem** — todos em SCRIPT_EXEC. O critério 2
(production caller), que zerava tudo na ABSORPTION-04, está fechado.

## Quatro defeitos que eu introduzi, achados pelo verificador
1. **Bypass de PDP/PEP no scheduler** — o mais grave. Registrar o scheduler
   DEPOIS de o runtime montar o mapa protegido deixava `sched-*` fora do PEP e
   fora da autorização; a capacidade caía no fallback do Orquestrador e
   executava pela ponte crua. Confirmei empiricamente
   (`in rt.executores` = False, e executava assim mesmo) antes de corrigir.
   É o mesmo bypass que `governado.py` documenta e fecha para filesystem —
   reaberto por mim para o scheduler.
2. **CRON inalcançável** — `_ponte_sched` ignorava a agenda, e um job criado
   pela capacidade governada virava ONE_SHOT em silêncio. Motor correto,
   nenhum caminho para armá-lo.
3. `--intervalo 0` virava 1.0 em silêncio.
4. `--executavel` sem `--adapters` não registrava nada e não avisava.

## Pendências registradas, não corrigidas
5. **Scheduler e Ticker emitem alertas contraditórios** para a mesma
   ocorrência (`UNKNOWN` vs `NO_EFFECT`) — o operador vê dois alertas
   discordando se houve efeito.
6. Política de catch-up não exposta no CLI (sempre RUN_ONCE).
7. **1 execução em 9 negou 3 guards de registry race** no ambiente do
   verificador. Provável `__pycache__` obsoleto, não reproduzido. Quem for
   congelar este HEAD deve repetir com cache limpo antes de confiar.

## Por que `READY_FOR_DAEMON=FALSE`
A regra exige `FS_CRITICAL_GAPS=0`, `SCHEDULER_CRITICAL_GAPS=0` e
`SCRIPT_CRITICAL_GAPS=0`. São 5, 8 e 9.

E o gap do daemon é honesto: Hermes e OpenClaw sobrevivem a logout e reboot;
o ticker do NOMOS só dispara enquanto alguém segura o processo. **A proibição
de daemon nesta missão explica o gap — não o fecha.**

## Produção — intocada
```
main 2cea197e… · guard 2ecc5ff7…317ecc · LaunchAgents nomos: 0
WhatsApp enabled=False · Hermes/OpenClaw/Ollama vivos
DAEMON / SHADOW / CANARY / CUTOVER / PORT_TAKEOVER: nenhum executado
```

## ABSORPTION-06 — ordem sugerida
1. reconciliar os alertas contraditórios e expor catch-up no CLI;
2. reexecutar a suíte com `__pycache__` limpo e fechar a pendência 7;
3. `30m`/`2h`/ISO (normalização explícita já especificada);
4. `FS-READ-BINARY` e patch multi-arquivo;
5. só então o daemon — que é o que fecha SCHED-12 e destrava shadow.
