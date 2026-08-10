# FASE 10 — FAIL-CLOSED REGRESSION

Os defeitos corrigidos na ABSORPTION-04 continuam fechados sobre o código novo.

| Defeito da 04 | Teste na 05 | Resultado |
|---|---|---|
| ticker aceitava `autorizador=None` | `test_ticker_sem_autorizador_continua_impossivel` | `ValueError` |
| `CatchUp.SKIP` rodava ocorrência velha | `test_catchup_skip_do_agendador_roda_a_mais_recente` | reagenda para o futuro |
| agenda corrompida virava ONE_SHOT | `test_agenda_corrompida_continua_fail_closed` | `ErroConflito: ilegível` |
| alerta só no ticker | (04) `test_scheduler_alerta_sem_depender_do_ticker` | evento emitido |

## Novos fail-closed desta missão
| Situação | Comportamento |
|---|---|
| agendador sem aprovador | `ErroRuntime` na construção |
| aprovador nega o registro | `ErroRegistro`; `capacidades==[]`, `_preparado==False` |
| ocorrência sem credencial | `ErroRuntime: sem autoridade` |
| capacidade sumiu do registro após criar o job | autorizador devolve `None`; evento `agendador.capacidade.sumiu` |
| `--scheduler`/`--executavel` sem `--raiz` | `E010`, nada registrado |
| `nomos scheduler` sem `--raiz` | `E010` |

## Direct execution
`test_caller_nao_alcanca_adapter_bruto`: todo executor do agendador é
`PontoDeAplicacao`. Nenhum callable cru exposto.

```
AUTHORIZER_FAIL_OPEN = FALSE
CORRUPT_SCHEDULE_FAIL_OPEN = FALSE
DIRECT_EXECUTOR_BYPASS = 0
```
