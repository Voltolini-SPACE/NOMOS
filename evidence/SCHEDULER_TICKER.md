# FASE 3 — TICKER / LOOP DE SCHEDULER

Commit `418bac5` · `src/nomos/adapters/ticker.py`

```
CLOCK → STORE → DUE → RESERVATION → AUTHORIZATION → PDP → PEP
      → BOUNDARY → CAPABILITY → AUDIT → FINALIZE
```

**Foreground e testável, não daemon.** A missão proíbe instalar serviço; o
ticker é a peça que um daemon futuro embrulha, e que aqui já roda sob teste com
relógio injetável.

## Requisitos — cada um com prova
| Requisito | Prova |
|---|---|
| polling controlado | `rodar_ate(max_ticks)` |
| clock injetável | `agora_fn` em todos os testes |
| shutdown limpo | `test_ticker_shutdown_limpo` — `parar()` interrompe em 2 ticks, não estoura o teto de 100 |
| **nenhuma busy-loop** | `test_ticker_nao_faz_busy_loop` — 4 ticks ⇒ 4 pausas de 0,25 s, inclusive sem trabalho |
| nenhuma execução sem reservation | dedup do scheduler; `test_ticker_nao_repete_ocorrencia` |
| recuperação após crash | `test_dedup_sobrevive_a_restart` (03) |
| dedup persistente | PRIMARY KEY em SQLite |
| catch-up explícito | ver abaixo |

## Catch-up — política formal, não comportamento implícito
Cenário: job de 5 em 5 minutos, máquina desligada 5 horas. Rodar 60 vezes? uma?
nenhuma? Deixar isso implícito é como o Hermes acumula surpresa.

| Política | Comportamento | Teste |
|---|---|---|
| `SKIP` | ignora as atrasadas, roda a mais recente | `test_catchup_skip_pula_as_antigas` |
| `RUN_ONCE` (default) | roda UMA vez e reagenda | `test_catchup_run_once_e_o_default` |
| `RUN_ALL_BOUNDED` | roda as perdidas até um teto | `test_catchup_run_all_bounded_respeita_o_teto` — teto 3 em vez de 60 |

## Cron + timezone atravessando o ticker
`test_ticker_com_cron_reagenda_no_fuso`: job `0 9 * * *` em
`America/Sao_Paulo` executa e reagenda para 2026-08-11 **12:00 UTC** — o
09:00 local. É o encontro das FASES 1, 2 e 3 num caminho só.

## Gates
```
TICKER_FUNCTIONAL=PASS
DUPLICATE_EFFECT=0
CRASH_RECOVERY=PASS
CATCHUP_POLICY_EXPLICIT=TRUE
BUSY_LOOP=FALSE
```
