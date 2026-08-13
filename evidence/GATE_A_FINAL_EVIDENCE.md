# NOMOS — GATE A · evidência final de convergência

Missão `NOMOS-GATE-A-CONVERGENCE-01`, encerrada em 2026-08-13.

## Bloco de gate

```
NOMOS_GATE_A_FINAL_EVIDENCE

BASELINE          = 0b2a1f2
FINAL_HEAD        = 298a03b
COMMITS           = 12 (0b2a1f2..298a03b)
BRANCH            = feat/nomos-c1-git-readonly
SRC_TREE_HASH     = df2bb12ef2e57049  (git ls-files -s -- src, sha256[:16])

P0_OPEN           = 0
P1_OPEN           = 0
P2_OPEN           = 0
INFO_OPEN         = 0

A7_A8_TOTAL       = 99
A7_A8_KILLED      = 99
A7_A8_SURVIVED    = 0
A7_A8_INVALID     = 0
A7_A8             = PASS

A9_RUNS           = 360  (12 cenários × 30)
A9_ESCAPES        = 0
A9                = PASS  (12/12)

A10               = 24/24
A10_ESCAPES       = 0
A10               = PASS

INDEPENDENT_SUITES = 5/5   (pytest-randomly, seeds 101/202/303/404/505)
FULL_SUITE        = 3578 passed, 24 skipped, 0 failed
RUFF              = PASS
SOURCE_CHECK      = PASS
WORKTREE_CLEAN    = PASS
CLONE_IDENTICO    = TRUE  (mutwt == wt por SHA-256, após a mutação)

GLOBAL_VECTORS    = 162   (universo r4 catálogo + achados)
GLOBAL_UNACCOUNTED = 0
GLOBAL_PINNED_BY_TEST_ID = 49
GLOBAL_COVERED_BY_AREA_SUITE = 113
GLOBAL_COVERAGE   = 100%  (contabilizado; ver ressalva)

GATE_A            = PASS
```

## O que a 4ª medição encontrou e esta missão fechou

35 achados confirmados após refutação adversarial (6 P0, 8 P1, 14 P2, 7 INFO),
todos fechados com prova antes/depois e teste de regressão permanente:

| classe | fechados | forma dominante |
|---|---|---|
| P0 | 6 | autoridade era STRING → liga por inode; attr.tree; token de filtro; self-gitdir |
| P1 | 8 | refs prof-2; janela-B em path-space; .11.09; teto de varredura; gitdir=wt |
| P2 | 14 | oráculo de existência; travessia por componente; config.worktree; FIFO 60s |
| INFO | 7 | 2 eram defeitos reais (N-A7-04 erro cru; FIFO em fonte de atributo); 5 classificados |

Detalhe por achado na genealogia de commits `0b2a1f2..298a03b`.

## Ressalvas honestas (não escondidas para bater o gate)

1. **Re-medição serial, não adversarial.** A 4ª medição usou painel de agentes
   refutadores. O limite semanal de subagentes está ativo até 2026-08-16, então
   a re-medição desta rodada é COBERTURA FORÇADA por inventário determinístico:
   todo vetor contabilizado, veredito explícito, zero omissão silenciosa. Ela é
   mais fraca que o painel — `GLOBAL_PINNED_BY_TEST_ID` (49, prova forte) é
   declarado separado de `GLOBAL_COVERED_BY_AREA_SUITE` (113, prova mais fraca:
   a suíte da área passa). O painel adversarial completo fica para 2026-08-16,
   por decisão de dono.

2. **A cobertura por área não re-mede cada vetor individualmente.** Os 113 são
   vetores fechados em rodadas anteriores, cobertos pela suíte temática que os
   exercita. Não afirmo re-medição individual deles nesta rodada.

## Landmines do próprio arnês, registradas

- `rsync`/`diff` via rtk reportaram "synced"/idêntico com 13 KB de diferença
  real → verificação de clone passou a ser por SHA-256 em Python.
- Restore por sinal do arnês de mutação não cobre SIGKILL → `conferir_clone_identico`
  no início é a defesa primária; o restore é best-effort.
- Âncora de mutante válida NÃO garante mutante que COMPILA → `conferir_mutantes_validos`
  pré-valida os 99 em milissegundos antes de rodar.
- `TMPDIR` customizado quebra o shim do Apple Git no sandbox (xcrun, rc=71) →
  independência das 5 suítes veio de `pytest-randomly`, não de TMPDIR.
