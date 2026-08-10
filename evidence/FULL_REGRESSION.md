# FASE 8 — FULL REGRESSION

```
FULL_TEST_SUITE = 2292 passed / 2306 coletados
FAILED  = 0
SKIPPED = 14
LINT    = PASS (ruff, src/ + tests/)
TYPECHECK = NOT_RUN — mypy não é dependência do projeto (o próprio repo marca
            os testes de mypy como skip; não introduzi a dependência)
STRUCTURAL_GUARDS = PASS
ADVERSARIAL = PASS
MUTATION = PASS (19/19)
```

## Evolução
| Missão | passed | skipped |
|---|---|---|
| baseline (02) | 2197 | 14 |
| ABSORPTION-03 | **2292** | 14 |

+95 testes: 36 filesystem · 23 scheduler · 13 race/timeout · 23 wiring.

## Classificação dos 14 skips — nenhum novo
```
PRE_EXISTING_ENVIRONMENTAL = 14
NEW_ENVIRONMENTAL          = 0
UNEXPECTED                 = 0
```
Motivos: namespaces do Linux (unshare/rootless) ×7 · mypy não é dependência ×2 ·
PyYAML não é dependência ×2 · SMTP fake frágil no macOS ×1 · Ollama ativo
torna um teste de fail-closed-sem-motor sem sentido ×1 · outro ambiental ×1.

O número de skips é **idêntico** ao baseline. Nenhum skip silencioso foi
introduzido, e nenhum teste foi marcado xfail.

## Ordem dos gates
`GATE A` (governança), `GATE D` (consistência) e `GATE E` (qualidade) passam.
`GATE B` (filesystem) e `GATE C` (scheduler) NÃO — ver `PARITY_MATRIX.md`.
