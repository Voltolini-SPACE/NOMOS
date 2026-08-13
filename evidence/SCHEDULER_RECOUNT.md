# FASE 7 — RECENSO DE SCHEDULER

**0 FULL / 15 PARTIAL / 2 MISSING / 1 FORA_DO_NUCLEO · 8 críticas em gap.**

Separando os quatro eixos que a missão pediu:

| Capacidade crítica | ENGINE | REACHABILITY | GOVERNANCE | PARITY |
|---|---|---|---|---|
| SCHED-02 CRON | ✅ | ✅ *(após `44c2a3c`)* | ✅ *(após `44c2a3c`)* | ❌ sem `30m`/`2h`/ISO |
| SCHED-03 INTERVALO | ✅ | ✅ | ✅ | ❌ idem |
| SCHED-07 PERSISTÊNCIA | ✅ | ✅ | ✅ | ⚠️ |
| SCHED-08 DEDUP | ✅ | ✅ | ✅ | ⚠️ |
| SCHED-11 EXEC-SCRIPT | ✅ | ✅ | ✅ | ❌ sem shell (decisão) |
| SCHED-12 DAEMON-TICKER | ✅ foreground | ✅ | ✅ | ❌ **não sobrevive a logout** |
| SCHED-15 ALERTA | ✅ | ✅ | ✅ | ❌ sem canal real + alertas contraditórios |
| SCHED-17 TIMEZONE | ✅ | ✅ *(após `44c2a3c`)* | ✅ | ⚠️ |

Antes de `44c2a3c`, REACHABILITY e GOVERNANCE de CRON/TIMEZONE eram ❌: a ponte
ignorava a agenda e as sched-* não passavam por PDP/PEP. As marcas ✅ com
ressalva são MINHAS, pós-censo — o verificador avaliou o HEAD anterior.

## O que impede FULL, por eixo
- **PARITY** é o eixo que trava tudo. O daemon (SCHED-12) é o caso mais claro:
  Hermes/OpenClaw sobrevivem a reboot; o NOMOS depende de alguém segurando o
  processo. Isso é diferença de RESULTADO, não de embalagem.
- `30m`/`2h`/ISO continuam ausentes (decisão registrada em `INPUT_PARITY.md`).
- Alertas contraditórios entre Scheduler e Ticker para a mesma ocorrência.

```
SCHEDULER_CRITICAL_GAPS = 8
SCHEDULER_UNGOVERNED    = 0 (após 44c2a3c; era >0 no HEAD avaliado)
```
