# FASE 9 — FAILURE ALERT NO CAMINHO DE RUNTIME

O alerta agora tem DUAS origens independentes, porque a 04 mostrou que ter só
uma deixava um caminho mudo:

| Origem | Cobre |
|---|---|
| `Scheduler._executar` → `_alertar` | falha por `executar_job()`/`executar_devidos()` |
| `Ticker._alertar` | falha de autorização e de execução via ticker |

## Casos cobertos
| Falha | Onde é detectada | `effect_state` |
|---|---|---|
| job failure (executor levanta) | scheduler + ticker | UNKNOWN |
| script timeout | adapter → ticker | UNKNOWN |
| authorization denial | ticker (`autorizador` → None) | NO_EFFECT |
| autorizador quebrado | ticker (exceção) | NO_EFFECT |
| capacidade removida (registry stale) | `agendador.autorizador` | NO_EFFECT |
| adapter error | scheduler + ticker | UNKNOWN |

## Evento
`scheduler.ocorrencia.falhou` com `job_id`, `occurrence_id`, `capability`,
`error_class`, `attempt`, `timestamp`, `effect_state`, `detalhe` (truncado em
300 caracteres, sem payload).

## Sem dependência de canal
`AuditAlertSink` grava na trilha hash-encadeada — o alerta herda integridade
sem infraestrutura nova. Nenhum import de rede no módulo (verificado por AST).
WhatsApp/e-mail não são exigidos nesta fase e não foram adicionados.

```
FAILURE_ALERT_RUNTIME_PATH=PASS
```
