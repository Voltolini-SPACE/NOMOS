# NOMOS-HERMES-OPENCLAW-ABSORPTION-03 — RELATÓRIO FINAL

## STATUS_FINAL = PARTIAL_BLOCKED_CRITICAL_GAP

```
BASELINE_HEAD=31742e7ad557c197540abc608660a9302a16d3b9   (ponta da ABSORPTION-02)
MAIN_HEAD=2cea197eb188121fcd507b53f02935b5edf435ad       (intocada)
MISSION_BRANCH=feat/nomos-absorption-03
COMMITS=13
WORKTREE_CLEAN=TRUE

FULL_TEST_SUITE=2292 passed / 2306 coletados
FAILED=0
SKIPPED=14   (todos PRE_EXISTING_ENVIRONMENTAL; nenhum novo)
LINT=PASS
TYPECHECK=NOT_RUN (mypy não é dependência do projeto)

PDP_MANDATORY=TRUE
PEP_MANDATORY=TRUE
DIRECT_MUTATING_BYPASS=0

FS_TOTAL=11          FS_FULL=0          FS_CRITICAL_GAPS=5
SCHEDULER_TOTAL=18   SCHEDULER_FULL=0   SCHEDULER_CRITICAL_GAPS=8

REGISTRY_RACE=PASS
NODE_HARD_TIMEOUT=PASS

TOTAL_CAPABILITIES=29 (nas 2 categorias remedidas)
FULL=0  PARTIAL=18  MISSING=8  FORA_DO_NUCLEO=3
CRITICAL_GAPS_REMAINING=13

MUTATION_TESTS=19/19 detectadas
REGRESSION=0

PRODUCTION_MUTATED=FALSE

READY_FOR_DAEMON=FALSE
READY_FOR_SHADOW=FALSE
READY_FOR_CANARY=FALSE
CUTOVER=FALSE
```

## Gates
| Gate | Critério | Resultado |
|---|---|---|
| **A — Governança** | PDP/PEP obrigatórios, bypass 0, default deny, path scope | ✅ **PASS** |
| **B — Filesystem** | `FS_CRITICAL_GAPS=0` | ❌ **FAIL — 5** |
| **C — Scheduler** | `SCHEDULER_CRITICAL_GAPS=0` | ❌ **FAIL — 8** |
| **D — Consistência** | registry race + timeout | ✅ **PASS** |
| **E — Qualidade** | suíte, lint, adversarial, mutation | ✅ **PASS** |

`PASS_CRITICAL_ADAPTER_LAYER` exige A+B+C+D+E. **B e C falham.**

## O que foi entregue
- **FASE 1** — contrato congelado: `CapabilityRequest/Context/Result` + erros
  tipados. `CapabilityContext` é frozen e só se constrói por `de_registro()`,
  que deriva risco e idempotência do REGISTRO.
- **FASE 2** — 8 capacidades de filesystem. `fs-ler` devolve CONTEÚDO com
  paginação por linha (o gap da 02); confinamento vale para TODAS, não só para
  escrita; escrita atômica temp+fsync+replace; `fs-editar` exige ocorrência
  única.
- **FASE 3** — scheduler com JobDefinition/State/Instance/Execution separados,
  máquina de estados allowlist, dedup por ocorrência que **sobrevive a
  restart** (reserva ANTES do efeito), e job que **não persiste autoridade**.
- **FASE 4** — registry race fechado: a autorização carimba a versão do
  descritor; capacidade removida, risco/idempotência alterados ou executor
  trocado ⇒ `CAPACIDADE_MUDOU`.
- **FASE 5** — timeout duro por nó com `EfeitoTimeout` explícito;
  `EFEITO_DESCONHECIDO` nunca autoriza retry.
- **Wiring** — capacidades registradas como DINÂMICAS (A5 + gate + audit), e
  expostas em produção por `nomos orquestrar --adapters --raiz`.

## Quatro defeitos reais encontrados — três deles no meu próprio código

1. **Bypass do PEP que o wiring abriu.** O `Orquestrador` cai em
   `registro.executor_de()` quando não acha o executor em `executores`; como
   `proteger_executores` só embrulhava os nativos, a capacidade dinâmica era
   executada pela ponte CRUA. Descoberto porque `pdp.decisao` não aparecia na
   trilha.
2. **Regressão de segurança:** `adapters=True` sem `caminhos` registrava
   fs-apagar/fs-mover com escopo vazio — **menos confinado** que o nativo que
   substitui. Agora fail-closed.
3. **PDP confinava por prefixo de string.** `/ws/../etc/passwd` passava. Grave
   porque as ferramentas NATIVAS não têm resolver próprio: ali o escopo do PDP
   era o único confinamento. Agora canoniza e contém por componente.
4. **`fs-listar` vazava `NotImplementedError` crua**, violando o contrato de
   erro tipado.

Os itens 2, 3 e 4 vieram do **recenso adversarial**, não da minha suíte. Foi
preciso alguém tentando derrubar.

## Blockers restantes — precisos

### Filesystem (5 críticas)
1. `FS-READ-BINARY` AUSENTE — sem equivalente ao `read-data-url` do Hermes.
2. `fs-editar` sem patch unificado/multi-arquivo nem diff auditável.
3. `arquivo_ler`/`arquivo_resumir` nativas seguem sem resolver próprio;
   protegidas só quando `--raiz` é usado.
4. Nenhuma linha atingiu GOVERNADO na recontagem — e **não declaro por conta
   própria**: exigiria reexecutar o censo depois das correções, o que não fiz.
5. Efeito colateral registrado: `_escrever_atomico` força 0600 também na
   edição, rebaixando o modo de um arquivo 0644.

### Scheduler (8 críticas)
6. **Cron real não existe** — há intervalo em segundos, não expressão cron.
7. **Timezone é armazenada, não aplicada** — cálculo é UTC puro.
8. **Sem daemon-ticker** — alguém precisa chamar `executar_devidos()`.
9. **Sem exec-script-sem-LLM** e **sem delivery/alerta de falha**.

### Fora do escopo desta missão
10. HTTP, CHANNELS, GIT e BROWSER não foram tocados; os 6 gaps críticos de
    HTTP/channels seguem para a ABSORPTION-04, como autorizado.

## Produção — intocada
```
main NOMOS   2cea197e…   (nenhum commit, merge, push, tag)
guard        2ecc5ff7051603675ccdf7ba087340759c246f26148a99b7db3be95628317ecc
Hermes :9119 vivo · OpenClaw :18789 vivo · Ollama :11434 vivo
WhatsApp enabled=False · antitamper carregado · ~/.hermes intacto
LaunchAgents com "nomos": 0
DAEMON_INSTALL / SHADOW / CANARY / CUTOVER / PORT_TAKEOVER: nenhum executado
```

## ABSORPTION-04 — ordem sugerida
1. cron real + timezone aplicada + ticker (fecha 3 das 8 críticas de scheduler);
2. reexecutar o censo para decidir GOVERNADO com verificação independente;
3. `fs-ler-bytes` e patch multi-arquivo;
4. adapters HTTP e channels;
5. só então daemon → shadow → canary.
