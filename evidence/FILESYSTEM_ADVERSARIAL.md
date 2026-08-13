# FASE 2 — SUÍTE ADVERSARIAL DE FILESYSTEM

`tests/test_absorption03_filesystem.py` — 36 testes.

| # | Ataque | Teste | Resultado |
|---|---|---|---|
| N1 | `../` | `test_n1_traversal_com_dotdot` | ErroEscopo |
| N2 | absoluto fora do root | `test_n2_absoluto_fora_do_root` | ErroEscopo |
| N3 | symlink interno → fora | `test_n3_symlink_interno_apontando_para_fora` | ErroEscopo |
| N3b | diretório-symlink para fora | `test_n3b_...` | ErroEscopo (motivo asseverado) |
| N4 | symlink trocado após validação | `test_n4_symlink_trocado_apos_validacao` | ErroEscopo na 2ª resolução |
| N5 | rename para fora | `test_n5_rename_para_fora` | ErroEscopo, nada movido |
| N6 | delete fora | `test_n6_delete_fora` | ErroEscopo, arquivo intacto |
| N7 | glob escapando root | `test_n7_glob_escapando_root` | filtrado, nada vaza |
| N8 | arquivo gigante | `test_n8_arquivo_gigante` | ErroLimite |
| N9 | arquivo inexistente | `test_n9_arquivo_inexistente` | ErroNaoEncontrado |
| N10 | permissão negada | `test_n10_permissao_negada` | erro tipado |
| N11 | escopo/prazo expirado | `test_n11_escopo_expirado_pelo_deadline` | ErroTimeout, sem efeito |
| N12 | auth válida para outro caminho | `test_n12_autorizacao_valida_para_outro_caminho` | ErroEscopo |
| N13 | replay | `test_n13_replay_de_leitura_nao_produz_efeito` | sem efeito |
| N14 | capacidade trocada após assinatura | `test_n14_capacidade_trocada_apos_assinatura` | ErroEscopo |

## Código morto removido pela mutação — e o que entrou no lugar

A primeira versão tinha `_exigir_cadeia_limpa()` para pegar diretório-symlink
apontando para fora. A mutação MF4 (remover a chamada) deixou **34/34 verdes**:
a checagem nunca executava, porque `os.path.realpath` já resolve links
intermediários mesmo com componente final inexistente — verificado
empiricamente (`raiz/dir -> /externo` + alvo `raiz/dir/novo.txt` resolve para
`/externo/novo.txt`).

Defesa que nunca roda produz confiança falsa. Removida.

No lugar entrou uma regra **mais estrita e exercitada**: mutação através de
symlink é recusada mesmo quando o link fica DENTRO do escopo — escrever em
`atalho.txt` mudaria `real.txt`, um alvo que o chamador não nomeou. Leitura via
link segue permitida; a recusa é só para efeito. MF4 refeita agora derruba o
teste correspondente.
