# FASE 1 — CENSO DE ÓRFÃOS (recontado, não presumido)

Recontagem no worktree da 05, antes de qualquer escrita.

| SYMBOL | DEFINED_AT | PRODUCTION_CALLERS | TEST_CALLERS | CLI_REACHABLE |
|---|---|---|---|---|
| `registrar_scheduler` | `adapters/wiring.py:188` | **0** | 1 | **NÃO** |
| `Ticker` | `adapters/ticker.py:65` | **0** | 1 | **NÃO** |
| `script-rodar` | `adapters/script.py` | 1 (condicional) | 1 | **NÃO** — `cli.py` nunca passava `executaveis` |
| `registrar_filesystem` | `adapters/wiring.py:79` | 1 (`runtime/governado.py`) | 0 | sim (`--adapters`) |
| `registrar_script` | `adapters/wiring.py:250` | 1 (condicional) | 1 | **NÃO** |
| `ScheduleSpec` | `adapters/agenda.py:246` | 2 (agenda, scheduler) | 2 | via scheduler |
| `AlertSink` | `adapters/alertas.py:57` | 3 (alertas, scheduler, ticker) | 1 | via scheduler |

**Confirmado**: o veredito da ABSORPTION-04 estava certo. `registrar_scheduler`
e `Ticker` eram órfãos completos; `script-rodar` tinha registro condicional que
o CLI jamais satisfazia.

Método: `grep` por definição e por chamada em `src/`, separando testes.
Nenhuma conclusão foi herdada do relatório anterior sem recontagem.
