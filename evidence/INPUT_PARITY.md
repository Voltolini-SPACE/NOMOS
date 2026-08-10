# FASE 8 — DIVERGÊNCIAS DE SEMÂNTICA: DECISÃO EXPLÍCITA

## 8.1 DST — contrato declarado
```
DST_NONEXISTENT_TIME_POLICY = SKIP_TO_NEXT_MATCHING_INSTANT
DST_AMBIGUOUS_TIME_POLICY   = FIRST_OCCURRENCE (fold=0)
```

**Decisão e por quê.** O censo da 04 me corrigiu: eu afirmava que horário
inexistente "vai para o primeiro instante real após a lacuna", mas isso só vale
para expressões que casam com os minutos pós-lacuna. Para horário FIXO
(`30 2 * * *` em Madri, 29/03) a ocorrência é **pulada** — o próprio teste
afirma `day == 30`.

Comparando com a fonte que o NOMOS substitui: o **Hermes usa `croniter`**, e o
croniter pula igual. Vixie cron rodaria o job logo após o salto. Como o alvo de
paridade é o Hermes, e não o Vixie, **mantive o comportamento** e corrigi a
DOCUMENTAÇÃO, que era o que estava errado.

Para horário ambíguo, `fold=0` faz o job rodar UMA vez. Rodar duas seria pior:
um job de fechamento financeiro executando em duplicidade é um incidente, não
uma redundância.

## 8.2 Sintaxe de entrada
| Forma | Hermes | NOMOS | Situação |
|---|---|---|---|
| cron numérico (`0 9 * * 1-5`) | sim | sim | paridade |
| nomes (`mon-fri`, `jan`) | **NÃO** (filtro `^[\d\*\-,/]+$`) | sim | NOMOS é superconjunto |
| `@daily`, `@hourly` | **NÃO** | sim | superconjunto |
| `30m`, `2h`, `1d` | sim | **não** | **gap residual** |
| timestamp ISO | sim | **não** | **gap residual** |

**Decisão: NÃO implementei o parser de duração/ISO nesta missão.** Motivo: ele
não está entre as 8 capacidades críticas de scheduler — as críticas são cron,
intervalo, persistência, dedup, exec-script, ticker, alerta e timezone, todas
tratadas. Adicionar um parser de string ambígua no fim de uma missão de wiring
seria trocar o alvo declarado por conveniência.

Fica registrado como gap específico, com a normalização proposta já definida
para a próxima missão:
```
"30m" → ScheduleSpec(INTERVAL, intervalo_s=1800)
"2h"  → ScheduleSpec(INTERVAL, intervalo_s=7200)
ISO   → ScheduleSpec(ONE_SHOT, primeiro_em=<parsed>)
```
Com a regra que já vale hoje: **nunca reinterpretar string ambígua em
silêncio** — `kind` continua explícito.

```
SCHEDULER_INPUT_PARITY = PARCIAL (gap residual documentado: 30m/2h/ISO)
```
