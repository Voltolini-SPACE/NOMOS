# NOMOS-HERMES-OPENCLAW-ABSORPTION-02 — RELATÓRIO FINAL

## STATUS_FINAL = PARTIAL_BLOCKED_CRITICAL_PARITY_GAP

```
BASELINE_HEAD=2cea197eb188121fcd507b53f02935b5edf435ad   (main; == origin/main)
MISSION_BASE=fb68220cd290eccc692d6714f8de9a7d84b0cb5d    (ponta da ABSORPTION-01)
MISSION_BRANCH=feat/nomos-absorption-02
COMMITS=8
WORKTREE_CLEAN=TRUE

FULL_TEST_SUITE=2197 passed / 2210 coletados
FAILED=0
SKIPPED=14           (ambientais e pré-existentes: namespaces Linux, mypy/PyYAML
                      fora das deps, SMTP frágil no macOS)
LINT=PASS (ruff, src/ + tests/)
TYPECHECK=NOT_RUN    (mypy não é dependência do projeto; skip é do baseline)

PDP_MANDATORY=TRUE
PEP_MANDATORY=TRUE
DIRECT_MUTATING_BYPASS=0
LEGACY_BOUNDARY_ONLY_ROUTES=0        (eram 2; fechadas na FASE 1)

HERMES_PARITY=5,4 %   (4 GOVERNADO de 74 aplicáveis — recalculado do zero)
OPENCLAW_PARITY=9,1 % (5 GOVERNADO de 55 aplicáveis)
CRITICAL_GAPS=18

PROVIDER_REAL=TRUE    (Ollama vivo, qwen2.5-7b-ptctx; E2E com motor real PASSED)
DAEMON_READY=FALSE
SHADOW_EXECUTED=FALSE
SHADOW_EXTERNAL_EFFECTS=0
ROLLBACK_PROVEN=TRUE  (para o escopo desta missão: nada a desfazer)

READY_FOR_SHADOW=FALSE
READY_FOR_CANARY=FALSE
CUTOVER=FALSE
```

## Gates

| Gate | Critério | Resultado |
|---|---|---|
| **A — Runtime** | suíte, lint, security, adversarial, mutation | ✅ **PASS** |
| **B — Governança** | PDP/PEP obrigatórios, bypass 0, default deny | ✅ **PASS** |
| **C — Paridade** | `CRITICAL_HERMES_GAPS=0` e `CRITICAL_OPENCLAW_GAPS=0` | ❌ **FAIL — 18 gaps críticos** |
| **D — Operacional** | daemon, restart, rollback, shadow safe | ❌ **FAIL — daemon não existe** |

`READY_FOR_SHADOW` exige A+B+C+D. **C e D falham** ⇒ `PARTIAL_BLOCKED`.

## O que foi entregue

| Fase | Estado | Commit |
|---|---|---|
| 0 — Rebaseline | ✅ | — |
| 1 — Fechar rotas legadas | ✅ | `9db3027` |
| 2 — Censo de capacidades | ✅ | `CAPABILITY_MATRIX.json` (114 capacidades) |
| 3 — Adapters nativos | ❌ NÃO EXECUTADA | — |
| 4 — Provider abstraction | ✅ | `fd69ef2` |
| 5 — Motor real E2E | ✅ | `b36e88a` |
| 6 — Daemon | ❌ NÃO EXECUTADA | — |
| 7 — Shadow | ❌ NÃO EXECUTADA | — |
| 8 — Adversarial E2E | ⚠️ 20/30 cobertos | — |
| 9 — Parity gate | ✅ recalculado | `PARITY_MATRIX.md` |
| 10 — Preparação de produção | ⚠️ parcial (rollback runbook) | — |

Commits: `9db3027` (rotas legadas) · `fd69ef2` (provider) · `b36e88a` (E2E) ·
`12a5384` (fix do escopo do PDP) · 4 de evidência.

## A paridade caiu de 58 % para 5 % — e isso é correção, não regressão

A ABSORPTION-01 reportou 58 % / 50 % sobre uma matriz de **24 linhas grossas**.
Este censo tem **114 linhas** com exigência de equivalência COMPORTAMENTAL e
verificação adversarial (6 agentes instruídos a REFUTAR alegações sem
evidência). "Git" era 1 linha; agora são 19, todas AUSENTE.

A missão mandou não carregar os valores antigos. Carregá-los teria escondido
18 gaps críticos atrás de um número confortável.

## Defeito encontrado pelo censo — no código desta própria missão

`decisor.py` sempre soube validar `pedido.recurso` e o contrabando por
`argumentos.alvo/caminho/destino` contra `autorizacao.caminhos`. Mas
`sessao_pdp` emitia a autorização **sem preencher o campo**, e o default é
`()` — com tupla vazia o bloco inteiro é pulado. **O escopo por caminho do PDP
estava inalcançável na prática.** Corrigido em `12a5384`, com 3 testes; a
mutação que restaura a regressão derruba 2 deles.

## Blockers restantes — lista precisa

### Bloqueiam GATE C (paridade)
1. **18 capacidades críticas com gap** (`PARITY_MATRIX.md`): 8 de scheduler,
   4 de channels, 4 de filesystem, 2 de HTTP.
2. **Nenhum adapter construído** (FASE 3). Sem fs-amplo, scheduler, http, git,
   channels e browser, a paridade não sai do lugar.
3. **`arquivo_ler` não é confinado** — só a escrita passa por
   `_resolver_destino_seguro`; leitura aceita caminho absoluto arbitrário.
4. **`arquivo_ler` não devolve conteúdo** — devolve metadado + bullets, e só
   aceita 7 extensões + PDF até 5 MB.

### Bloqueiam GATE D (operacional)
5. **Não existe daemon** — sem serviço, `SINGLE_INSTANCE`, `CRASH_RECOVERY`,
   `REBOOT_RECOVERY` e `DAEMON_REMOVABLE` não podem sequer ser medidos.
6. **Shadow não executável** — depende de 2 e 5.
7. **Sem timeout duro por nó** — `recuperacao.py` sempre apontou o sandbox como
   responsável; o contrato de adapter da FASE 3 precisa implementá-lo.

### Lacunas de cobertura adversarial (8 de 30)
8. **registry race** e **capability removed after planning** — lacunas reais e
   baratas de fechar; não dependem de adapter.
9. HTTP destination, redirect escape, Git destructive, channel spoofing,
   scheduler duplicate, daemon restart, stale auth after restart — **atacam
   superfícies que ainda não existem**. Testá-las agora seria teatro.
10. **symlink escape** e **concurrent replay** cobertos por construção
    (`.resolve()`, lock no `ArmazemNonce`) mas **sem teste dedicado**.

## Produção — intocada, verificado no fecho
```
main NOMOS   2cea197e…  (nenhum commit, merge, push, tag)
guard        2ecc5ff7051603675ccdf7ba087340759c246f26148a99b7db3be95628317ecc
Hermes :9119 vivo · OpenClaw :18789 vivo
WhatsApp enabled=False · antitamper carregado
~/.hermes intacto (toolchain Node depende dele)
LaunchAgents com "nomos": 0
```
`PRODUCTION_MUTATED=FALSE` · `FINANCIAL_RULES_CHANGED=FALSE` ·
`GUARDS_PRESERVED=TRUE`

## Próxima missão — ABSORPTION-03
Ordem por alavancagem sobre os 18 gaps críticos:
1. adapters **fs-amplo** (4 críticas) e **scheduler** (8 críticas) — fecham 12 de 18;
2. contrato de adapter com timeout, erro tipado e audit trail;
3. fechar registry race e capability-removed-after-planning;
4. adapters http → git → channels → browser;
5. só então daemon → shadow → adversarial E2E completo → canary.

Hermes e OpenClaw permanecem ativos e obrigatórios durante toda a 03.
