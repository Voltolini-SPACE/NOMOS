# FASE 9 — REGISTRY RACE (regressão)

`tests/test_absorption03_race_timeout.py` — **13 passed** sobre o código da 04.

O ataque temporal continua fechado depois de cron, ticker e script:
```
authorize A → mutate registry → execute
```

| Mudança entre emissão e execução | Motivo devolvido |
|---|---|
| capacidade removida | `CAPACIDADE_DESCONHECIDA` / `CAPACIDADE_MUDOU` |
| risco alterado | `CAPACIDADE_MUDOU` |
| idempotência alterada | `CAPACIDADE_MUDOU` |
| adapter/executor trocado | `CAPACIDADE_MUDOU` |
| `versoes` forjada | `ASSINATURA_INVALIDA` (quebra o HMAC) |

## Cobertura de jobs persistentes
Um job agendado é o caso mais exposto ao race: ele nasce em T0 e executa em T2,
por definição. Duas defesas independentes atuam:
1. **autoridade por ocorrência** (FASE 4) — o ticker pede credencial fresca em
   T2, então uma política que mudou em T1 vale;
2. **`versoes` do descritor** (ABSORPTION-03) — mesmo com credencial fresca, se
   o descritor da capacidade mudou, o PDP nega.

## Lacuna honesta
O escopo de caminho (`caminhos`) alterado entre emissão e execução **não** é
coberto por `versoes` — a impressão digital cobre nome, categoria, idempotência
e executor, não o escopo da autorização. Na prática a autorização fresca por
ocorrência resolve, porque ela é emitida com o escopo de T2. Mas não há teste
dedicado a "path scope changed" em job persistente. **Registrado como gap**, não
declarado coberto.

```
REGISTRY_RACE=PASS
SCHEDULED_STALE_DESCRIPTOR=DENY
PATH_SCOPE_CHANGED_EM_JOB_PERSISTENTE=NAO_TESTADO
```
