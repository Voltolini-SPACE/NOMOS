# FASE 2 — TIMEZONE REALMENTE APLICADA

## O que mudou
A ABSORPTION-03 **armazenava** `tz` e calculava em UTC. O censo foi direto:
"guardar a string sem usá-la NÃO é suporte a timezone". Agora o cálculo do
próximo disparo acontece **no fuso declarado**, e só então converte para UTC.

## Prova comportamental
`0 9 * * *` — mesmo cron, três fusos, três instantes reais:
| Timezone | Próximo disparo (UTC) |
|---|---|
| `UTC` | 2026-08-11 **09:00** |
| `America/Sao_Paulo` (UTC−3) | 2026-08-11 **12:00** |
| `Europe/Madrid` (UTC+2 em agosto) | 2026-08-11 **07:00** |

Se a timezone fosse decorativa, os três seriam 09:00.

## DST — os dois casos difíceis, tratados explicitamente
**Horário inexistente** (primavera, o relógio pula). Madri 2026-03-29:
02:00→03:00, então 02:30 não existe. Um job `30 2 * * *` não pode sumir nem
disparar em hora errada — `_normalizar_local` detecta a lacuna pela ida-e-volta
da conversão e avança para o primeiro instante REAL. Verificado: o disparo cai
em 30/03 02:30.

**Horário ambíguo** (outono, o relógio volta). Madri 2026-10-25: 02:30 acontece
DUAS vezes. Usamos `fold=0`, a primeira ocorrência, para o job rodar **uma**
vez. Verificado: dispara em 25/10 02:30 e o seguinte é 26/10 — não a segunda
passagem do mesmo relógio.

**São Paulo** não tem mais DST desde 2019; o teste confirma offset estável em
janeiro e julho, o que também protege contra alguém "consertar" DST onde não há.

## Timezone desconhecida ⇒ DENY
`resolver_tz` recusa `Marte/Olympus`, `GMT-3`, vazio e `america/sao paulo`
(minúscula com espaço). Nunca há fallback silencioso para UTC ou para o fuso do
host — o que seria a falha mais traiçoeira, porque só aparece em produção.

## Gates
```
TIMEZONE_APPLIED=TRUE
UNKNOWN_TIMEZONE=DENY
DST_BEHAVIOR_TESTED=TRUE      (inexistente + ambíguo, em Europe/Madrid)
RESTART_TIMEZONE_STABLE=TRUE
```
