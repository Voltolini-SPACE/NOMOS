# FASE 11 — ADVERSARIAL CONTRA O WIRING

| # | Ataque | Teste | Resultado |
|---|---|---|---|
| 1 | CLI registra scheduler sem PDP | `test_registro_e_o_MESMO_que_o_planner_consulta` | usa o registro autoritativo |
| 2 | ticker com autorizador falso/None | `test_ticker_sem_autorizador_continua_impossivel` | `ValueError` |
| 3 | caller invoca adapter direto | `test_caller_nao_alcanca_adapter_bruto` | todos são PEP |
| 4 | `--executavel` aponta para symlink | `test_validar_executaveis_resolve_symlink` | guarda o realpath |
| 5 | executável trocado após o registro | `test_executavel_trocado_depois_do_registro_nao_e_aceito` | recusado |
| 6 | cwd escapa do escopo | `test_script_cwd_fora_do_escopo_e_negado` | negado |
| 7 | job referencia capacidade removida | `test_capacidade_removida_apos_criar_job_nega_a_ocorrencia` | autorizador nega |
| 8 | ticker executa após mudança de política | `test_autorizacao_negada_no_instante_da_execucao` (04) | 0 efeitos |
| 9 | timeout deixa efeito UNKNOWN | `test_script_timeout_pela_cadeia` | "desconhecido" no detalhe |
| 10 | registry não carregado após restart | `test_agenda_corrompida_continua_fail_closed` | fail-closed |
| 11 | ocorrência duplicada | `test_ticker_nao_repete_ocorrencia` (04) | 1 efeito |
| 12 | CLI omite parâmetro obrigatório | `test_cli_scheduler_exige_raiz` | `E010` |
| 13 | dinâmica sobrescreve nativa | `test_capacidade_dinamica_nao_sobrescreve_nativa` | ver nota |
| 14 | colisão de ID de capacidade | `test_id_de_capacidade_colidido_e_recusado` | "já registrada" |
| 15 | registro parcial após erro | `test_registro_parcial_apos_erro_nao_deixa_meia_capacidade` | estado limpo |

## Nota sobre o ataque 13 — dois guards, não um
Das 8 ferramentas nativas, **só `doutor` passa `NOME_RE`**
(`^[a-z][a-z0-9-]{1,31}$` — sem underscore). As outras 7 são barradas pela
validação de NOME, antes de a checagem "sombrear nativa é proibido" ser
alcançada.

A proteção existe nos dois casos, mas por motivos diferentes — e o teste agora
cobre os dois caminhos explicitamente, além de varrer as 8. Chamar isso de "um
guard só" seria impreciso; e a checagem de sombreamento estaria a um rename de
virar código morto.
