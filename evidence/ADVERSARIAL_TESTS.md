# SUÍTE ADVERSARIAL — 47 testes ofensivos

Commit: `a54af4a test(nomos): add adversarial authorization and bypass suite`
Arquivo: `tests/test_pdp_adversarial.py`

## Cobertura exigida pela missão

| Ataque | Teste | Resultado |
|---|---|---|
| forged token | `test_token_forjado_com_chave_errada_e_negado` | DENY |
| expired token | `test_token_expirado_e_negado` | DENY |
| token replay | `test_replay_do_envelope_inteiro_e_negado` | DENY |
| nonce replay | `test_nonce_repetido_e_negado` | DENY |
| wrong capability | `test_capacidade_nao_concedida_e_negada` | DENY |
| wrong subject | `test_sujeito_errado_e_negado` | DENY |
| wrong resource | `test_recurso_fora_do_escopo_e_negado` | DENY |
| wrong arguments | `test_argumento_contrabandeia_recurso_e_negado` | DENY |
| scope widening | `test_atenuacao_nao_consegue_alargar_capacidades` | intersectado |
| privilege escalation | `test_atenuacao_nao_consegue_subir_risco_nem_prazo` | limitado ao pai |
| malformed authorization | `test_autorizacao_de_tipo_errado_e_negada` | DENY |
| missing authorization | `test_sem_autorizacao_e_negado` | DENY |
| PDP unavailable | `test_relogio_quebrado_nega_sem_propagar` | DENY (ERRO_INTERNO) |
| nonce store unavailable | `test_armazem_de_nonce_indisponivel_nega` | DENY |
| corrupted state | `test_registro_que_explode_nega_sem_propagar` | DENY |
| adapter direct call | `test_pep_nao_expoe_o_executor_bruto` | inalcançável |
| planner → capacidade privilegiada | `test_planner_nao_alcanca_capacidade_privilegiada` | rejeitado |
| graph node → escalação | `test_no_do_grafo_nao_escala_privilegio` | ErroGrafo |
| recovery após DENY | `test_recuperacao_nao_reexecuta_apos_deny` | tentativas=0 |
| retry burlando policy | `test_retry_proibido_para_capacidade_nao_idempotente` | 1 tentativa |
| entry point alternativo | `test_entrada_alternativa_no_runtime_nao_pula_o_pdp` | grafo recusa |
| reflection/atributo | `test_pep_nao_pode_ganhar_atributo_novo` | AttributeError |
| direct route bypass | `test_rotas_ate_o_adapter_sao_exatamente_estas` | censo fixado |
| internal-call bypass | `test_executor_injetado_ainda_passa_pelo_pep` | via PEP |
| serialization tampering | `test_adulteracao_pos_assinatura_invalida_a_assinatura` | HMAC quebra |

## Os testes têm dentes — verificado por MUTAÇÃO

Suíte adversarial que passa de primeira é suspeita. Cada defesa central foi
removida e a suíte precisou acusar:

| Mutação aplicada | Testes que falharam |
|---|---|
| validação de idempotência no grafo → `if False` | 3 |
| PEP ignorando a decisão (`if not decisao.permitido` → `if False`) | 3 |
| assinatura não verificada | 3 |
| capacidade concedida não conferida | 2 |

Todas revertidas após a verificação.

## Dois testes foram CORRIGIDOS por passarem pelo motivo errado

`test_entrada_alternativa_no_runtime_nao_pula_o_pdp` e
`test_runtime_com_autorizacao_expirada_nao_produz_efeito` originalmente
asseveravam só o desfecho ("não escreveu"). Sob mutação, continuavam verdes —
porque quem barrava era **outra** defesa (`DestinoInseguroError`, o guard de
destino de `arquivo_escrever`), não a que o teste alegava provar.

Corrigidos para asseverar o MOTIVO (`missao is None` + `"grafo inválido"`;
`Motivo.EXPIRADA` no detalhe do nó). Depois da correção, a mutação faz os dois
falharem — que é o comportamento correto de um teste com dentes.

Isto é defesa em profundidade funcionando (duas barreiras independentes), mas
um teste que não isola a sua barreira não prova nada sobre ela.
