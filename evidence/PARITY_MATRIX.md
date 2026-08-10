# FASE 9 — PARITY GATE (recalculado do zero)

Fonte: `evidence/CAPABILITY_MATRIX.json` — censo da FASE 2 com 7 agentes de
categoria + 6 verificadores adversariais instruídos a REFUTAR alegações de
paridade sem evidência. 114 capacidades, cada linha com `evidencia`
(arquivo:linha ou comando) e `production_dependency`.

**Os valores da ABSORPTION-01 (58 % / 50 %) NÃO foram carregados.** Eles vieram
de uma matriz de 24 linhas grossas; esta tem 114 linhas com exigência de
equivalência COMPORTAMENTAL. A diferença não é regressão — é resolução.

## Totais
```
GOVERNADO       7
PARCIAL        30
AUSENTE        53
FORA_DO_NUCLEO 24     (shell/PTY/subprocess: decisão de arquitetura, não lacuna)
TOTAL         114
```

## Por categoria
| Categoria | GOVERNADO | PARCIAL | AUSENTE | FORA_DO_NUCLEO |
|---|---|---|---|---|
| FILESYSTEM | 0 | 4 | 5 | 2 |
| GIT | 0 | 0 | **19** | 1 |
| HTTP | 4 | 7 | 5 | 0 |
| SCHEDULER/JOBS | 0 | 7 | 10 | 1 |
| BROWSER | 1 | 3 | 5 | 2 |
| CHANNELS | 0 | 5 | 9 | 1 |
| PROCESSO/TERMINAL | 2 | 4 | 0 | 17 |

## Paridade
```
HERMES_TOTAL=89        (linhas com Hermes como origem, incl. "ambos")
HERMES_FULL=4
HERMES_PARTIAL=24
HERMES_MISSING=46
HERMES_FORA_DO_NUCLEO=15
HERMES_PARITY = 4/74 aplicáveis ≈ 5,4 %      (excluindo FORA_DO_NUCLEO)

OPENCLAW_TOTAL=62
OPENCLAW_FULL=5
OPENCLAW_PARTIAL=26
OPENCLAW_MISSING=24
OPENCLAW_FORA_DO_NUCLEO=7
OPENCLAW_PARITY = 5/55 aplicáveis ≈ 9,1 %
```

## Critério de shadow — NÃO atingido
```
critical_capability_missing      = 18   (exigido: 0)
mutating_capability_without_pdp  = 0    ✅
known_policy_bypass              = 0    ✅
known_uncontrolled_executor      = 0    ✅
```

### As 18 capacidades críticas com gap
| Status | Categoria | Capacidade |
|---|---|---|
| AUSENTE | CHANNELS | sendPolicy por sessão · antitamper WhatsApp · pairing/allowlist de canal |
| PARCIAL | CHANNELS | recebimento Telegram |
| AUSENTE | FILESYSTEM | edição cirúrgica / patch |
| PARCIAL | FILESYSTEM | leitura de conteúdo · escrita/criação · **confinamento de caminho** |
| PARCIAL | HTTP | probe de serviço loopback · canal de mensageria com long-poll |
| AUSENTE | SCHEDULER | cron recorrente · recorrente por intervalo · exec script sem LLM · daemon ticker · timezone |
| PARCIAL | SCHEDULER | persistência · dedup/idempotência · delivery e alerta de falha |

## Achados do censo que mudaram o código desta missão
1. **Escopo por caminho do PDP estava inalcançável.** `decisor.py` sempre soube
   validar `pedido.recurso` e o contrabando por `argumentos.alvo`, mas
   `sessao_pdp` nunca preenchia `caminhos` — com tupla vazia o bloco era
   pulado. Corrigido em `12a5384`, com 3 testes e mutação que restaura a
   regressão derrubando 2 deles.
2. **`arquivo_ler` não é confinado.** Só a ESCRITA passa por
   `_resolver_destino_seguro`; a leitura aceita caminho absoluto arbitrário.
   Registrado como PARCIAL, não como paridade de leitura.
3. **`arquivo_ler` não devolve conteúdo** — devolve `(formato · N caracteres)`
   e bullets heurísticos, e só aceita 7 extensões de texto + PDF até 5 MB.
   Hermes `read_file` devolve conteúdo numerado com offset/limit. Chamar isso
   de paridade de leitura seria falso.
4. **OpenClaw está com filesystem DESCONFINADO na config viva** (`tools.fs`
   ausente ⇒ `workspaceOnly:false`), com 615 de 1087 chamadas `write`
   registradas fora do workspace declarado. É contexto de risco do ambiente —
   nada foi alterado.
