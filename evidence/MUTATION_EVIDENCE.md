# MUTATION EVIDENCE — as defesas foram removidas, uma a uma

Suíte de segurança usada (baseline **113 passed**):
`test_pdp_adversarial.py` · `test_runtime_governado.py` ·
`test_absorption02_rotas_legadas.py` · `test_absorption02_provider_security.py` ·
`test_absorption02_e2e_runtime.py`

| # | Defesa mutada | Alvo | Resultado |
|---|---|---|---|
| M1 | validação de idempotência do nó no grafo | `orquestracao/grafo.py` | **3 failed** |
| M2 | PEP ignora a decisão do PDP | `pdp/pep.py` | **6 failed** |
| M3 | assinatura HMAC não verificada | `pdp/decisor.py` | **3 failed** |
| M4 | capacidade concedida não conferida | `pdp/decisor.py` | **2 failed** |
| M5 | expiração ignorada | `pdp/decisor.py` | **4 failed** |
| M6 | nonce/anti-replay ignorado | `pdp/decisor.py` | **5 failed** |
| M7 | audiência ignorada | `pdp/decisor.py` | **2 failed** |
| M8 | escopo de recurso ignorado | `pdp/decisor.py` | **2 failed** |
| M9 | teto de risco ignorado | `pdp/decisor.py` | **1 failed** |
| M10 | default-deny → default-allow | `pdp/decisor.py` | **12 failed** |
| M11 | limpeza de autoridade do provider removida | `runtime/inferencia.py` | **2 failed** |
| M12 | boundary removido do adapter | `runtime/governado.py` | **2 failed** |
| M13 | `sessao_pdp` volta a ignorar `caminhos` | `runtime/governado.py` | **2 failed** |
| M14 | contrabando por argumento não checado | `pdp/decisor.py` | **1 failed** |

**14/14 mutações detectadas.** Todas revertidas após a medição (verificado:
suíte volta a 2197 passed e `git status` limpo).

## O harness também precisou ser provado

A primeira execução da bateria reportou "0 failed (NÃO PEGOU!)" nas quatro
primeiras mutações. **Não eram as defesas — era o harness.** Duas causas, nesta
ordem:

1. passei `--timeout=120` sem `pytest-timeout` instalado ⇒ pytest saía com erro
   de uso e nenhuma linha "N failed" era produzida;
2. corrigido isso, veio "no tests ran": em **zsh não há word-split** de variável
   não citada, então `$SUITES` chegava ao pytest como UM argumento só. Resolvido
   com array (`"${SUITES[@]}"`).

Registrado porque é o tipo de erro que produz um falso "tudo seguro": um
resultado verde vindo de comando que nem rodou. Toda a tabela acima foi medida
depois da correção, com baseline explícito (113 passed) para comparação.

## Testes que passavam pelo motivo errado (corrigidos na ABSORPTION-01)

Dois testes chegavam ao resultado certo por OUTRA defesa (`DestinoInseguroError`
do guard de destino), não pela que alegavam provar. Foram reescritos para
asseverar o MOTIVO (`missao is None` + `"grafo inválido"`; `Motivo.EXPIRADA` no
detalhe do nó). Depois da correção, a mutação correspondente os derruba.
