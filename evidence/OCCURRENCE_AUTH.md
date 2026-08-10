# FASE 4 — AUTORIZAÇÃO POR OCORRÊNCIA

## O problema
```
job created at T0  →  policy changes at T1  →  occurrence at T2
```
A execução em T2 tem de refletir o estado autoritativo de T2. Um job que
carregasse token de T0 seria autorização eterna — exatamente o que o modelo
recusa.

## A solução
O ticker **não guarda credencial**. Para CADA ocorrência ele chama
`autorizador(definicao, instancia)` e recebe autoridade fresca, que entrega ao
`scheduler.executar_ocorrencia(..., credencial=...)`. O scheduler repassa e não
retém.

## Provas
| Caso | Teste | Resultado |
|---|---|---|
| autorizador é chamado por ocorrência | `test_autorizador_e_chamado_por_ocorrencia` | 2 ocorrências ⇒ 2 chamadas, credenciais distintas |
| política mudou entre criação e execução | `test_autorizacao_negada_no_instante_da_execucao` | 0 efeitos |
| autorizador quebrado | `test_autorizador_que_explode_nao_produz_efeito` | 0 efeitos + evento `NO_EFFECT` |
| credencial não é persistida | `test_job_nao_persiste_credencial` | dump do SQLite (jobs + ocorrencias) não contém o token |
| job não tem campo de autoridade | `test_job_persistido_nao_carrega_autorizacao` (03) | nem no dataclass nem nas colunas |

## Ligação com a FASE 9 (registry race)
A `Autorizacao` emitida carrega `versoes` — a impressão digital do descritor de
cada capacidade (ABSORPTION-03). Se risco, idempotência ou executor mudarem
entre a emissão e o uso, o PDP nega com `CAPACIDADE_MUDOU`. Autoridade fresca
por ocorrência **e** descritor conferido: são defesas diferentes para problemas
diferentes, e as duas atuam.

## Gates
```
PERSISTED_ETERNAL_AUTH=FALSE
PER_OCCURRENCE_AUTH=TRUE
STALE_JOB_AUTH=DENY
```
