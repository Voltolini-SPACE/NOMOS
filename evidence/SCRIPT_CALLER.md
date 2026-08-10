# FASE 4 — CALLER PARA `script-rodar`

## A lacuna da 04
```
script-rodar só registra `if executaveis:`
cli.py nunca passava executaveis
```

## Fechada
`nomos orquestrar --adapters --raiz <dir> --executavel /caminho/bin` — a flag
pode repetir. Sem ela a capacidade **não é registrada**; não existe
`--allow-any-executable`.

## Allowlist canonicalizada — `wiring.validar_executaveis()`
Cada entrada é provada AGORA:
| Checagem | Recusa |
|---|---|
| existe | `ValueError: executável não existe` |
| é arquivo regular (não diretório) | `é diretório, não executável` |
| tem bit de execução | `sem bit de execução` |
| não é interpretador de shell | `é interpretador de shell` |
| vira `realpath` | — guarda o caminho REAL |
| duplicatas | normalizadas para uma entrada |

Guardar o **realpath** é o que fecha o TOCTOU de symlink: trocar o link depois
do registro não autoriza o novo alvo
(`test_executavel_trocado_depois_do_registro_nao_e_aceito`).

E a allowlist é **fixada no registro**, não vem do plano — um passo hostil com
`executaveis` próprio é recusado.

## Efeito real pela cadeia
`test_script_efeito_real_pela_cadeia`: `pdp.decisao` → `pep.aplicacao` →
`script.fim`, com stdout do processo. Casos negativos cobertos: executável fora
da allowlist, cwd fora do escopo, timeout (efeito DESCONHECIDO), saída truncada.

## Gates
```
SCRIPT_RUN_PRODUCTION_CALLER = 1
SCRIPT_ALLOWLIST_EXPLICIT = TRUE
SCRIPT_ALLOW_ANY_DEFAULT = FALSE
```
