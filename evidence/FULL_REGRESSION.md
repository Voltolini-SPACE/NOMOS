# FASE 13 — FULL REGRESSION

```
FULL_TEST_SUITE = 2424 passed / 2437 coletados
FAILED  = 0
SKIPPED = 14
LINT    = PASS (ruff, src/ + tests/)
TYPECHECK = NOT_RUN — mypy não é dependência do projeto
STRUCTURAL_GUARDS = PASS
ADVERSARIAL = PASS
MUTATION = PASS (11/11)
```

## Evolução
| Missão | passed | skipped |
|---|---|---|
| ABSORPTION-02 | 2197 | 14 |
| ABSORPTION-03 | 2292 | 14 |
| ABSORPTION-04 | 2382 | 14 |
| **ABSORPTION-05** | **2424** | **14** |

+42 testes: `test_absorption05_callers.py`.

## Skips — nenhum novo
```
PRE_EXISTING_ENVIRONMENTAL = 14
NEW_ENVIRONMENTAL          = 0
UNEXPECTED                 = 0
```
Número idêntico nas quatro missões. Nenhum xfail, nenhum teste enfraquecido.

## Gate de consistência docs/site
Adicionar `nomos scheduler` como comando de usuário fez o gate `mc33` reprovar
até o site documentá-lo — 9 testes vermelhos. É o guard do repo funcionando, e
foi atendido documentando o comando, não silenciando o teste.
