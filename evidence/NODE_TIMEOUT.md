# FASE 5 — TIMEOUT DURO POR NÓ

Commit: `34645e8`

## Mecanismo
`CapabilityContext.deadline_monotonic` (relógio monotônico — imune a ajuste de
hora do sistema) + `exigir_prazo()`, chamado por `Adapter._coerente` ANTES de
qualquer trabalho. Prazo estourado ⇒ `ErroTimeout` e **nenhum efeito**
(`test_deadline_estourado_impede_inicio` verifica que o arquivo não é criado).

`wiring._ponte` calcula o deadline por chamada (`timeout_s`, default 30 s), de
modo que cada NÓ tem prazo próprio — não é timeout do provider.

## Classificação explícita
```python
class EfeitoTimeout:
    SEM_EFEITO           = "TIMED_OUT_NO_EFFECT"
    EFEITO_DESCONHECIDO  = "TIMED_OUT_EFFECT_UNKNOWN"
    EFEITO_CONFIRMADO    = "TIMED_OUT_EFFECT_CONFIRMED"
```
"Deu timeout" não é resposta: o que importa é se o mundo mudou. O tipo existe
para que `EFEITO_DESCONHECIDO` não seja lido como "não aconteceu nada".

## Retry após timeout
Nunca vem do plano. A decisão de repetir é do REGISTRO — a mesma defesa da
ABSORPTION-01, reverificada aqui
(`test_retry_apos_timeout_nunca_vem_do_plano`).

E idempotência **não** implica que um efeito parcial foi revertido: ela
autoriza REPETIR, não afirma que nada ficou pela metade. Por isso
`EFEITO_DESCONHECIDO` não entra no conjunto seguro
(`test_efeito_desconhecido_nao_e_idempotente_por_definicao`).

## Gates
```
NODE_HARD_TIMEOUT=PASS
TIMEOUT_RETRY_FROM_PLAN=FALSE
MUTATING_UNKNOWN_EFFECT_AUTO_RETRY=FALSE
```

## Cobertura honesta
Coberto: adapter que demora, filesystem que bloqueia, prazo já vencido na
entrada. **Não** coberto por teste dedicado: provider pendurado e audit
travado — o deadline os alcançaria pelo mesmo mecanismo, mas sem teste eu não
declaro. Registrado como lacuna.
