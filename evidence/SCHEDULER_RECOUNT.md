# FASE 8 — SCHEDULER REVALIDATION (independente)

**0 FULL / 15 PARTIAL / 2 MISSING / 1 FORA_DO_NUCLEO · 8 críticas em gap.**
As mesmas 8 da ABSORPTION-03 — mas 5 delas saíram de AUSENTE para PARTIAL com
implementação real e provada.

| Capacidade crítica | 03 | 04 | O que falta |
|---|---|---|---|
| SCHED-02 CRON | MISSING | **PARTIAL** | caller de produção |
| SCHED-03 INTERVALO | PARTIAL | PARTIAL | caller de produção |
| SCHED-07 PERSISTÊNCIA | PARTIAL | PARTIAL | caller de produção |
| SCHED-08 DEDUP | PARTIAL | PARTIAL | caller de produção |
| SCHED-11 EXEC-SCRIPT | MISSING | **PARTIAL** | flag `--executavel` no CLI |
| SCHED-12 DAEMON-TICKER | MISSING | **PARTIAL** | daemon (proibido nesta missão) |
| SCHED-15 ALERTA | MISSING | **PARTIAL** | caller + canal real |
| SCHED-17 TIMEZONE | MISSING | **PARTIAL** | caller de produção |

## Os 8 defeitos que o censo achou — 4 corrigidos, 4 registrados
| # | Defeito | Estado |
|---|---|---|
| D1 | ticker fail-open (`autorizador=None` executava) | **CORRIGIDO** `d7badbc` |
| D2 | ticker silencioso por default (sem audit nem sink) | **CORRIGIDO** (D4 cobre) |
| D3 | `CatchUp.SKIP` executava ocorrência VELHA | **CORRIGIDO** `d7badbc` |
| D4 | alerta só existia no ticker | **CORRIGIDO** `d7badbc` |
| D5 | downgrade silencioso de CRON → ONE_SHOT | **CORRIGIDO** `d7badbc` |
| D6 | docstring de DST superestima o comportamento | **REGISTRADO** — ver abaixo |
| D7 | ocorrência falhada nunca repete | **REGISTRADO** |
| D8 | `*/1` conta como dom restrito (edge do OR) | **REGISTRADO** — croniter faz igual |

### D6 — correção de uma afirmação minha
Eu escrevi que horário inexistente "vai para o primeiro instante real após a
lacuna". **Isso só vale para expressões que casam com os minutos pós-lacuna.**
Para horário fixo (`30 2 * * *` em Madri, 29/03) a ocorrência é PULADA — o meu
próprio teste afirma `local.day == 30`. Vixie cron rodaria o job logo após o
salto; o NOMOS (como o croniter) pula o dia. Comportamento defensável, mas a
docstring prometia mais do que entrega.

### D7 — lacuna real
A reserva pré-efeito fica gravada como FAILED e bloqueia nova tentativa. Somado
a D2/D4 (já corrigidos), uma ocorrência podia falhar e sumir sem retry e sem
aviso. O alerta agora existe; **o retry de ocorrência falhada continua ausente**
e é item da próxima missão.

## Divergência com o Hermes que o censo mediu
O `parse_schedule` do Hermes usa `croniter` mas filtra com
`^[\d\*\-,/]+$` — ou seja, **o Hermes REJEITA nomes** (`mon-fri`, `jan`) e
atalhos (`@daily`), que o NOMOS aceita. Em cron o NOMOS é superconjunto; em
parsing de string de duração (`30m`, `2h`, ISO) é subconjunto — não existe
parser dessas formas.
