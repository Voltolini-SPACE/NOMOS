# FASE 4 — REGISTRY RACE

Commit: `34645e8`

## O ataque
```
plan(capability=A) → authorization(A) → registry muda → execute
```
A execução não pode usar metadata obsoleta de risco/idempotência.

## A estratégia escolhida: versão do descritor na autorização

`versao_de_capacidade(registro, cap)` = SHA-256 de
`nome | categoria | idempotência | identidade do executor`, truncado em 16 hex.

`sessao_pdp()` carimba `Autorizacao.versoes` no instante da emissão. O
`Decisor` recomputa na decisão e nega com `CAPACIDADE_MUDOU` se divergir.

Escolhi versão-no-token em vez de snapshot imutável ou revalidação separada
porque ela viaja COM a autorização: já é coberta pela assinatura HMAC, então
adulterar a versão quebra o contrato (`test_versao_forjada_nao_passa`) e não
exige um segundo armazenamento a manter coerente.

## Detecção — cada caso com teste
| Mudança | Teste | Motivo devolvido |
|---|---|---|
| capacidade removida | `test_capacidade_removida_apos_emissao_e_negada` | CAPACIDADE_DESCONHECIDA ou CAPACIDADE_MUDOU |
| idempotência alterada | `test_idempotencia_alterada_apos_emissao_e_negada` | CAPACIDADE_MUDOU |
| risco alterado | `test_risco_alterado_apos_emissao_e_negado` | CAPACIDADE_MUDOU |
| adapter/executor trocado | `test_executor_trocado_apos_emissao_e_negado` | CAPACIDADE_MUDOU |
| versão forjada | `test_versao_forjada_nao_passa` | ASSINATURA_INVALIDA |

## Compatibilidade
Autorização sem `versoes` (legada) continua válida: o guard só age quando há o
que comparar (`test_autorizacao_sem_versoes_continua_valida`). Isso é uma
escolha de compatibilidade, e está registrada — uma autorização antiga não
ganha proteção retroativa.

## Gates
```
REGISTRY_RACE_COVERED=TRUE
STALE_CAPABILITY_AUTH=DENY
REMOVED_CAPABILITY=DENY
MUTATED_RISK_METADATA=DENY
```
