# FASE 5 — EXEC-SCRIPT SEM LLM (e sem shell)

Commits `418bac5` + `cdc5f62` · `src/nomos/adapters/script.py`

## Contrato
```
argv[]        lista, NUNCA string
cwd           obrigatório, confinado por ctx.raizes
env           ALLOWLIST (PATH, HOME, LANG, LC_ALL, TZ, TMPDIR)
timeout       obrigatório, ≤600s, kill de grupo (start_new_session)
stdin         DEVNULL
saída         256 KB por fluxo, truncada com marca explícita
executaveis   allowlist opcional; FIXADA no registro quando wired
```

## Proibições — por construção, não por validação de string
`subprocess.run` recebe uma LISTA com `shell=False`. Não existe caminho para o
shell interpretar nada. Consequência testada: metacaractere em ARGUMENTO é
texto inerte.

| Payload | Resultado |
|---|---|
| `; rm -rf /` · `&& rm -rf /` · `\|\| whoami` | chegam literais ao programa |
| `$(whoami)` · `` `whoami` `` | idem, não expandem |
| `\| cat /etc/passwd` · `> /tmp/invadido` | idem; o arquivo não é criado |
| `\n rm -rf /` | idem |

Shell como `argv[0]` (`sh`, `bash`, `zsh`, `/bin/sh`, `cmd.exe`…) é **recusado**:
rodar shell é OUTRA capacidade, com outro risco, não um argumento desta.

| Ataque | Teste | Resultado |
|---|---|---|
| cwd fora do escopo | `test_cwd_continua_confinado_pelo_escopo_de_dados` | ErroEscopo |
| env injection | `test_env_fora_da_allowlist_e_recusado` | `LD_PRELOAD` recusado |
| vazamento de ambiente | `test_ambiente_e_confinado_por_allowlist` | `NOMOS_SEGREDO` não chega ao filho |
| timeout | `test_timeout_mata_o_processo` | sleep(30) morto em 0,5 s |
| saída gigante | `test_saida_grande_e_truncada` | 500 KB truncados |
| allowlist ampliada pelo plano | `test_allowlist_de_executaveis_nao_vem_do_plano` | recusado |

## Correção de desenho registrada
A primeira versão confinava o **executável** às raízes de DADOS. Estava errado:
obrigaria copiar o Python para dentro do workspace. Escopo de dados diz onde
LER/ESCREVER; quem autoriza RODAR é o gate — `script-rodar` é `A5_CODE_EXEC`.
A allowlist de binários é a camada extra, e o `cwd` segue confinado.

## Caminho de produção
`registrar_script` é fail-closed nos dois eixos: exige `raizes` **e**
`executaveis`. A allowlist é fixada no registro, não vem do chamador — quem
executa não define o próprio limite.
`test_script_alcancavel_pelo_runtime_governado` prova efeito real com
`pdp.decisao` → `pep.aplicacao` → `script.fim` na trilha.

## Gates
```
SCRIPT_EXECUTION_GOVERNED=TRUE
SHELL_IMPLICIT=FALSE
TIMEOUT=PASS
ENVIRONMENT_CONFINED=TRUE
```
