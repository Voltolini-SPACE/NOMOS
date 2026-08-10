# FASE 7 — MUTATION EVIDENCE

Formato exigido: `DEFENSE_MUTATED / EXPECTED_TESTS_RED / OBSERVED_RED / PASS`.

## Baterias

### Filesystem (baseline 34→36 passed)
| Defesa mutada | Esperado | Observado | PASS |
|---|---|---|---|
| canonicalização (`realpath`→`abspath`) | ≥1 | 3 | ✅ |
| contenção por componente → prefixo de string | ≥1 | 1 | ✅ |
| escopo não verificado | ≥1 | 8 | ✅ |
| guard de symlink na escrita | ≥1 | 1 | ✅ |
| coerência pedido/contexto | ≥1 | 2 | ✅ |
| deadline não exigido | ≥1 | 1 | ✅ |

### Scheduler (baseline 23 passed)
| Defesa mutada | Esperado | Observado | PASS |
|---|---|---|---|
| dedup: reserva sempre concede | ≥1 | 3 | ✅ |
| guard DISABLED/CANCELLED | ≥1 | 2 | ✅ |
| transição inválida aceita | ≥1 | 2 | ✅ |
| reserva DEPOIS do efeito (`INSERT OR REPLACE`) | ≥1 | 3 | ✅ |
| `devidos()` ignora estado | ≥1 | 3 | ✅ |

### Registry race / timeout (baseline 49 passed)
| Defesa mutada | Esperado | Observado | PASS |
|---|---|---|---|
| checagem de versão removida | ≥1 | 3 | ✅ |
| versões não carimbadas na emissão | ≥1 | 1 | ✅ |
| versão ignora idempotência | ≥1 | 1 | ✅ |
| versão ignora executor | ≥1 | 1 | ✅ |
| `exigir_prazo` desligado | ≥1 | 2 | ✅ |

### Correções do recenso (baseline 81 passed)
| Defesa mutada | Esperado | Observado | PASS |
|---|---|---|---|
| PDP volta ao prefixo de string | ≥1 | 2 | ✅ |
| mutante sem raiz volta a ser permitido | ≥1 | 1 | ✅ |
| padrão absoluto volta a passar | ≥1 | 1 | ✅ |

**19 defesas mutadas, 19 detectadas.** Todas revertidas após a medição.

## Falso verde — duas vezes, e como foi pego

A primeira execução da bateria reportou "0 failed (NÃO PEGOU!)" em quatro
defesas. **Não eram as defesas — era o harness**, por duas causas em sequência:

1. `--timeout=120` sem `pytest-timeout` instalado ⇒ pytest sai com erro de USO
   e nenhuma linha "N failed" é produzida;
2. corrigido isso, veio "no tests ran": em **zsh não há word-split** de
   variável não citada, então `$SUITES` chegava como UM argumento. Resolvido
   com array (`"${SUITES[@]}"`).

Toda a tabela acima foi medida depois da correção, sempre com baseline
explícito impresso antes — sem o baseline, "0 failed" é indistinguível de
"nada rodou".

## Defesa que era código morto

`_exigir_cadeia_limpa()` (filesystem) sobreviveu à mutação: removê-la deixou
34/34 verdes. `os.path.realpath` já resolve links intermediários mesmo com
componente final inexistente, então a checagem principal sempre chegava antes.
Removida e substituída por um guard mais estrito (recusa de mutação através de
symlink) que **é** exercitado.
