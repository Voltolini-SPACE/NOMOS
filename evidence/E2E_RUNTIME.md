# FASE 5 — E2E COM MOTOR REAL

Commit: `b36e88a test(nomos): end-to-end runtime chain with real inference engine`

Ambiente: `MODELS_LOCAL` remontado, Ollama `:11434` com 11 modelos.
Modelo usado: `qwen2.5-7b-ptctx:latest`.

## Cadeia exercitada
```
prompt → planner → DAG → registry → PDP → PEP → boundary → adapter
       → effect → audit → result
```

## Casos e resultados (15 testes, todos PASS)

| # | Caso | Resultado observado |
|---|---|---|
| 1 | read allow | nó OK; trilha com pdp.decisao → pep.aplicacao → agente.ferramenta.usada |
| 2 | write allow autorizado | **efeito real**: `workspace/saida.txt` criado com o conteúdo |
| 3 | write deny | nó NEGADO; arquivo não existe |
| 4 | write fora do workspace | `DestinoInseguroError`; nada criado |
| 5 | path traversal `../../` | recusado; nada criado fora |
| 6 | unknown capability | plano fail-closed; `missao is None` |
| 7 | authorization expirada | detalhe do nó contém `expirada` |
| 8 | replay | 1ª ALLOW, 2ª `NONCE_REPETIDO` |
| 9 | dependency failure | `mau` FALHOU → `dep` BLOQUEADO |
| 10 | DAG parcial | `bom` OK enquanto `mau` FALHOU e `dep` BLOQUEADO |
| 11 | retry idempotente (A0) | 3 tentativas |
| 12 | sem retry em mutante (A1) | 1 tentativa |
| 13 | provider failure | plano fail-closed; nada executa |
| 14 | orçamento de tentativas | total ≤ 4, anti retry-storm |
| 15 | **motor real** | PASSED (não pulado) — verificado com `-v -rs` |

No caso 15, cada passo é reconferido: `categoria is FERRAMENTAS[ferramenta]` e
idempotência coerente com A0 — ou seja, nada do que o modelo devolveu virou
autoridade.

## Lacuna registrada, não mascarada
**Não existe timeout duro POR NÓ** no runtime. `recuperacao.py` já documentava
que timeout de execução é responsabilidade do sandbox (`runtime/sandbox`). O
limite verificado no caso 14 é o ORÇAMENTO de tentativas da missão, que é
anti-retry-storm — não substitui timeout. Consta como lacuna na matriz de
paridade e é item da próxima missão (contrato de adapter com timeout).
