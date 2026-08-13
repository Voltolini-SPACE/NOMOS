# FASE 1 — CRON REAL

Commit `418bac5` · `src/nomos/adapters/agenda.py` · 38 testes

## Cobertura da sintaxe exigida — verificada
| Expressão | Base 2026-08-10 12:30 UTC | Próximo disparo |
|---|---|---|
| `* * * * *` | | 12:31 |
| `*/5 * * * *` | | 12:35 |
| `0 * * * *` | | 13:00 |
| `0 9 * * 1-5` | | 2026-08-11 09:00 |
| `0 0 1 * *` | | 2026-09-01 00:00 |

Além do mínimo: listas (`1,15`), faixas com passo (`0-6/2`), nomes de mês
(`jan`) e de dia (`mon-fri`), atalhos (`@daily`, `@hourly`, `@monthly`…), e
`0`/`7` ambos como domingo.

## A regra do POSIX que quase toda implementação caseira erra
Quando **dia-do-mês E dia-da-semana** estão os dois restritos, cron usa **OR**,
não AND. `0 0 13 * fri` dispara no dia 13 **ou** em qualquer sexta.
`ExpressaoCron` guarda `dom_restrito`/`dow_restrito` justamente para isso, e
`test_semantica_or_entre_dom_e_dow` prova os três casos (dia 13 numa quinta,
sexta que não é 13, quarta que não é 13). Um AND aqui pularia disparos
legítimos silenciosamente.

## Fail-closed
17 expressões inválidas testadas (`60 * * * *`, `* 24 * * *`, `* * 0 * *`,
`*/0`, `5-1`, campo a mais, campo a menos, lixo…) — todas `ErroCron`.

`test_expressao_invalida_nao_persiste_nem_arma` vai além do parser: cria um job
com cron inválida e verifica que **nada foi gravado** e **nenhum job ficou
armado**. `ScheduleSpec.__post_init__` valida na construção, então a falha
acontece antes de qualquer persistência.

`0 0 30 2 *` (30 de fevereiro) é **recusada** com "não dispara nos próximos 5
anos" em vez de girar para sempre procurando.

## ScheduleSpec — cron nunca é inferido
```
kind: ONE_SHOT | INTERVAL | CRON
expression / timezone / intervalo_s
```
Uma string de cron só é tratada como cron quando `kind=CRON` é declarado.
`test_nunca_infere_cron_de_string_arbitraria` prova que um ONE_SHOT com
`expression="0 9 * * *"` ignora a expressão.

## Persistência
Coluna `schedule` (JSON) com migração aditiva `ALTER TABLE` para bancos
anteriores. `test_cron_sobrevive_a_restart` prova que um novo processo lê a
agenda e recalcula o mesmo próximo disparo, no fuso certo. Jobs legados com
`intervalo_s` continuam funcionando.

## Gates
```
CRON_REAL=PASS
CRON_INVALID_FAIL_CLOSED=PASS
CRON_RESTART_PERSISTENCE=PASS
```
