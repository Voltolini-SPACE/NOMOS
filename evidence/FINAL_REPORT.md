# NOMOS-HERMES-OPENCLAW-ABSORPTION-04 — RELATÓRIO FINAL

## STATUS_FINAL = PARTIAL_BLOCKED_CRITICAL_GAP

```
BASELINE_HEAD=d6ec5d9f2164d72f775dc75b3142fc4ffe0ac1c2   (ponta da ABSORPTION-03)
MAIN_HEAD=2cea197eb188121fcd507b53f02935b5edf435ad       (intocada)
MISSION_BRANCH=feat/nomos-absorption-04
COMMITS=8
WORKTREE_CLEAN=TRUE

FULL_TEST_SUITE=2382 passed / 2395 coletados
FAILED=0
SKIPPED=14   (todos PRE_EXISTING_ENVIRONMENTAL; nenhum novo)
LINT=PASS
TYPECHECK=NOT_RUN (mypy não é dependência do projeto)

PDP_MANDATORY=TRUE
PEP_MANDATORY=TRUE
DIRECT_MUTATING_BYPASS=0

CRON_REAL=PASS
TIMEZONE_APPLIED=TRUE
TICKER_FUNCTIONAL=PASS
PER_OCCURRENCE_AUTH=TRUE   (e agora fail-closed: o autorizador é obrigatório)

SCRIPT_EXECUTION_GOVERNED=TRUE
FAILURE_ALERTS=PASS

REGISTRY_RACE=PASS
NODE_HARD_TIMEOUT=PASS

FS_TOTAL=11         FS_FULL=0         FS_CRITICAL_GAPS=5   FS_UNGOVERNED=ver matriz
SCHEDULER_TOTAL=18  SCHEDULER_FULL=0  SCHEDULER_CRITICAL_GAPS=8

TOTAL_CAPABILITIES=29
FULL=0  PARTIAL=23  MISSING=3  FORA_DO_NUCLEO=3
GOVERNED=12  UNGOVERNED=9  NA=8
CRITICAL_GAPS_REMAINING=13

MUTATION_TESTS=15/15 (11 da FASE 11 + 4 das correções do censo)
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
| **A — Governança** | PDP/PEP obrigatórios, bypass 0, default deny | ✅ **PASS** |
| **B — Filesystem** | `FS_CRITICAL_GAPS=0` · `FS_UNGOVERNED=0` | ❌ **FAIL — 5 gaps** |
| **C — Scheduler** | cron, timezone, ticker, per-occurrence auth, gaps=0 | ⚠️ **PARCIAL** — os 4 primeiros PASS, `SCHEDULER_CRITICAL_GAPS=8` |
| **D — Execução** | script governado, timeout, registry race | ✅ **PASS** |
| **E — Qualidade** | suíte, lint, adversarial, mutation | ✅ **PASS** |

`PASS_SCHEDULER_RUNTIME_PARITY` exigiria `SCHEDULER_CRITICAL_GAPS=0`. São 8.

## O que foi construído — e funciona
- **Cron real**: parser completo, com a semântica **OR do POSIX** entre
  dia-do-mês e dia-da-semana. Nenhuma lib de cron existe no ambiente e o NOMOS
  tem 2 dependências no total; escrevi o parser em vez de puxar a terceira.
- **Timezone aplicada**: o cálculo acontece no fuso IANA declarado.
  `0 9 * * *` dá 09:00 UTC, 12:00 UTC (São Paulo) e 07:00 UTC (Madri) — se
  fosse decorativa, os três seriam iguais. DST inexistente e ambíguo tratados.
- **Ticker**: foreground, clock injetável, shutdown limpo, sem busy-loop,
  catch-up explícito (SKIP/RUN_ONCE/RUN_ALL_BOUNDED).
- **Autorização por ocorrência**, agora **fail-closed por construção**.
- **`script-rodar`**: argv[] sem shell, 8 payloads de metacaractere provados
  inertes, env por allowlist, timeout com kill de grupo, allowlist de binário
  fixada no registro.
- **Alertas**: evento estruturado, canal desacoplado, sem import de rede.

## O que o censo independente disse — e eu não sobrescrevi
**0 FULL.** O motivo é um só e é estrutural: **falta caller de produção**.
`registrar_scheduler()` não tem caller em `src/`; o `Ticker` só existe no
próprio módulo e no teste; `script-rodar` só registra `if executaveis:` e o
`cli.py` nunca passa isso — não há flag `--executavel`.

Construí o motor. Não liguei o fio. Isso é exatamente a distinção que a
ABSORPTION-03 me ensinou e que eu repeti.

## Oito defeitos meus, achados por quem tentou derrubar
Quatro **corrigidos** neste commit (`d7badbc`):
1. **Ticker fail-open** — `autorizador=None` era default e executava com
   credencial nula. Invariante que se desliga por omissão não é invariante.
2. Ticker silencioso por default.
3. **`CatchUp.SKIP` executava ocorrência VELHA** com downtime longo. Meu teste
   só conferia `len(chamadas)==1` e por isso passava.
4. **Alerta só existia no ticker** — falha por `executar_job()` era 100% muda,
   e a minha docstring afirmava o contrário.
5. **Downgrade silencioso de CRON** — agenda corrompida virava ONE_SHOT e o job
   parava de recorrer sem avisar.

Quatro **registrados, não corrigidos**:
6. Minha docstring de DST **superestima**: "primeiro instante após a lacuna" só
   vale para expressões que casam com os minutos pós-lacuna; para horário fixo
   a ocorrência é pulada (Vixie cron rodaria).
7. **Ocorrência falhada nunca repete** — a reserva pré-efeito bloqueia retry.
8. `*/1` conta como dia-do-mês restrito no OR (croniter faz igual).

## Blockers para a ABSORPTION-05
1. **Ligar o fio**: caller de produção para `registrar_scheduler` e para o
   `Ticker`; flag `--executavel` no `nomos orquestrar`. Sem isso nada vira FULL.
2. Retry de ocorrência falhada (D7).
3. `FS-READ-BINARY`; patch multi-arquivo com diff auditável.
4. Timeout do alert sink e da ocorrência de scheduler (hoje indireto).
5. Escopo de caminho alterado em job persistente — não coberto por `versoes`.
6. HTTP, CHANNELS, GIT, BROWSER: 6 críticas da 02, intocadas.

## Produção — intocada
```
main 2cea197e… · guard 2ecc5ff7…317ecc · Hermes/OpenClaw/Ollama vivos
WhatsApp enabled=False · antitamper carregado · LaunchAgents nomos: 0
DAEMON_INSTALL / SHADOW / CANARY / CUTOVER / PORT_TAKEOVER: nenhum executado
```
