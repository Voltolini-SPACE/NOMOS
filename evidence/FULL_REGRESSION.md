# FASE 12 — FULL REGRESSION

```
FULL_TEST_SUITE = 2377 passed / 2390 coletados
FAILED  = 0
SKIPPED = 14
LINT    = PASS (ruff, src/ + tests/)
TYPECHECK = NOT_RUN — mypy não é dependência do projeto; o próprio repo marca
            os testes de mypy como skip. Não introduzi a dependência só para
            marcar um campo.
STRUCTURAL_GUARDS = PASS
ADVERSARIAL = PASS
MUTATION = PASS (11/11 nesta missão; 19/19 herdadas revalidadas)
```

## Evolução
| Missão | passed | skipped |
|---|---|---|
| ABSORPTION-02 | 2197 | 14 |
| ABSORPTION-03 | 2292 | 14 |
| **ABSORPTION-04** | **2377** | **14** |

+85 testes nesta missão: 38 agenda (cron/timezone) · 47 ticker/script/alertas.

## Classificação dos 14 skips — nenhum novo
```
PRE_EXISTING_ENVIRONMENTAL = 14
NEW_ENVIRONMENTAL          = 0
UNEXPECTED                 = 0
```
Número **idêntico** ao das três missões anteriores. Motivos: namespaces do
Linux (unshare/rootless) ×7, mypy não é dependência ×2, PyYAML não é
dependência ×2, SMTP fake frágil no macOS ×1, Ollama ativo torna sem sentido um
teste de fail-closed-sem-motor ×1, outro ambiental ×1.

Nenhum skip silencioso foi introduzido, nenhum teste marcado xfail, nenhum
teste enfraquecido para ficar verde.
