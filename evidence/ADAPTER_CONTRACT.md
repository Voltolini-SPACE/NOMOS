# FASE 1 — CONTRATO DE ADAPTER CONGELADO

Commit: `822efd6` · `src/nomos/adapters/contrato.py`

```
CapabilityRequest   o que se quer (capacidade, alvo, argumentos)  — DADO
CapabilityContext   contexto JÁ AUTORIZADO (frozen)               — AUTORIDADE
CapabilityResult    ok, valor, efeito_aplicado, metadados
ErroCapacidade      escopo · não-encontrado · permissão · limite ·
                    inválido · timeout · conflito
```

## O que o adapter NÃO pode — e como isso é imposto

| Proibição | Mecanismo |
|---|---|
| atribuir risco | `CapabilityContext` só se constrói por `de_registro()`, que lê `registro.risco_de()` |
| declarar idempotência | idem, via `registro.idempotente_de()` |
| emitir autorização | o módulo não importa nada de `pdp`; verificado por AST na ABSORPTION-02 e por ausência de import aqui |
| alterar escopo | `raizes` é campo de dataclass **frozen** |
| executar capacidade desconhecida | `de_registro()` levanta `ErroInvalido` se `not registro.conhecida()` |
| executar capacidade diferente da autorizada | `Adapter._coerente` compara `pedido.capacidade` com `ctx.capacidade` |
| ignorar prazo | `_coerente` chama `ctx.exigir_prazo()` antes de qualquer efeito |

## Gates
```
RAW_MUTATING_EXECUTOR_REACHABLE=FALSE
  — `test_capacidade_dinamica_nao_escapa_do_pep`: toda capacidade executável
    pelo runtime é um `PontoDeAplicacao`
ADAPTER_ASSIGNS_RISK=FALSE          (test_contexto_deriva_risco_e_idempotencia_do_registro)
ADAPTER_ASSIGNS_IDEMPOTENCY=FALSE   (idem)
ADAPTER_SIGNS_AUTH=FALSE            (contrato.py não importa nem chama `pdp`)
```

`versao_de_capacidade()` já nasce aqui — é a peça que a FASE 4 usa para o
registry race.
