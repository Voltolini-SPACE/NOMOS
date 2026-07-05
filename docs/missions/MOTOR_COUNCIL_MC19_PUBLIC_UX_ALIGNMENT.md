# MOTOR COUNCIL MC19 — DOCUMENTATION/PUBLIC UX ALIGNMENT FOR CLI + CHAT DRY-RUN

## 1. Status final

STATUS_FINAL=PASS_MOTOR_COUNCIL_MC19_PUBLIC_UX_ALIGNMENT

Documentação pública e textos de ajuda alinhados ao estado real: o Motor
Council tem `simular` em dry-run **na CLI e no chat**, enquanto execução real,
policy/audit/vault reais, cloud e persistência continuam desligados. README,
índice técnico, UX spec e chat dry-run spec atualizados; a linha de `/ajuda`
do chat e um comentário interno do `cli.py` corrigidos (help text), com dois
testes de help adicionados. Nenhum runtime funcional novo, nenhum refactor
CLI/Chat, nenhuma tag/release/PyPI. Suíte: 884 → 886.

## 2. Baseline

| Item | Resultado |
|---|---|
| BASELINE_HEAD | 760655a |
| BASELINE_TAG | v1.3.0rc4-motor-council-dry-run-14-g760655a |
| GIT_STATUS | CLEAN (antes das mudanças) |
| GIT_FSCK | PASS (1 commit dangling pré-existente, benigno) |
| RUFF | PASS |
| PYTEST | PASS_884 (antes) → PASS_886 (depois) |
| BUILD | PASS_IN_TMP_SANDBOX_FS_QUIRK |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | WARN (LOG_LEGACY_UNANCHORED, esperado) |
| COBERTURA | 86% (≥ 80%) |

## 3. Escopo

```text
PUBLIC_DOCS_ALIGNMENT=true
CLI_DRY_RUN_ALREADY_AVAILABLE=true
CHAT_DRY_RUN_ALREADY_AVAILABLE=true
REAL_ENGINE_EXECUTION=false
REAL_POLICY=false
REAL_AUDIT=false
REAL_VAULT=false
PERSISTENCE=false
```

## 4. Arquivos atualizados

| Arquivo | Mudança |
|---|---|
| `README.md` | seção `## Motor Council` reescrita (CLI + chat `simular` em dry-run; o resto desabilitado); contagem de testes 778 → 884 e nota de maturidade ajustada |
| `docs/architecture/MOTOR_COUNCIL_INDEX_v1.md` | novo bloco "Estado de UX/superfícies" (MC14–MC18 PASS, `CLI_DRY_RUN_AVAILABLE=true`, `CHAT_DRY_RUN_AVAILABLE=true`, `REAL_EXECUTION_AVAILABLE=false`, `PRODUCTION_READY=false`); nota no roadmap sobre a duplicação controlada CLI/Chat e a fase de refactor separada (MC20) |
| `docs/architecture/MOTOR_COUNCIL_UX_SPEC_v1.md` | status `IMPLEMENTATION=partial` + seção "Current implementation status" (mapa por comando: disabled vs dry-run) |
| `docs/architecture/MOTOR_COUNCIL_CHAT_DRY_RUN_SPEC_v1.md` | status `IMPLEMENTATION=MC18_DONE` / `CHAT_DRY_RUN_ENABLED=true`; nota do que foi implementado vs. o que segue bloqueado; regras de segurança preservadas |
| `src/nomos/simple/amigavel.py` | **help text**: linha do `/ajuda` trocada de "Motor Council (pré-release, ainda DESABILITADO)" para "/conselho simular <texto> — dry-run (simula, sem execução real)" |
| `src/nomos/cli.py` | **comentário interno** desatualizado (MC14) corrigido para descrever o roteamento MC15 (só `simular` em dry-run); nenhum código executável, output ou help do argparse mudou |
| `tests/council/test_chat_conselho_dry_run.py` | +2 testes de help (`test_chat_ajuda_mentions_conselho_simular_dry_run`, `test_cli_help_mentions_conselho_simular_dry_run`) |
| `docs/missions/MOTOR_COUNCIL_MC19_PUBLIC_UX_ALIGNMENT.md` | este relatório |
| `CHANGELOG.md` | entrada `[Unreleased]` (Documentation / Changed / Not changed) |

## 5. Estado documentado

- **CLI dry-run**: `nomos conselho simular "..."` (MC15-UX) — disponível.
- **Chat dry-run**: `/conselho simular ...` (MC18-UX) — disponível.
- **Ainda bloqueado** nas duas superfícies: `conselho`/`/conselho` sem
  subcomando e `perguntar`/`revisar`/`status`/`modos`/`explicar`/
  `diagnostico` (desabilitados/fail-closed).
- **Execução real**: desligada (`REAL_LOCAL_ENGINE_EXECUTION_ENABLED = False`,
  sem API); sem policy/audit/vault reais; sem cloud/rede/subprocess; sem
  persistência; prompt/conteúdo nunca exibido.
- **Release**: `v1.3.0rc4-motor-council-dry-run`, **pre-release**, não-latest.
- **PyPI**: não publicado.

## 6. Help text

Alterado (dentro do permitido pela missão):

- `amigavel.py` `/ajuda`: a linha do Council agora aponta para
  `/conselho simular <texto>` como dry-run, em vez de dizer só "DESABILITADO".
- `cli.py`: um **comentário** desatualizado (dizia que qualquer uso de
  `conselho` era bloqueado) foi corrigido para refletir o roteamento MC15. O
  `help=` do subparser `conselho` **já** dizia "só `simular` (dry-run), demais
  subcomandos DESABILITADOS" desde a MC15 — não precisou mudar.

Testes de guarda adicionados: o `/ajuda` do chat e o `nomos --help` são
verificados por teste para mencionar `conselho simular` + `dry-run`. Nenhuma
lógica de roteamento foi tocada.

## 7. O que NÃO foi feito

- sem runtime funcional novo
- sem refactor/unificação entre `cli_dry_run.py` e `chat_dry_run.py`
- sem alteração de comportamento em `cli_dry_run.py`/`chat_dry_run.py`/
  `orchestrator.py`/`local_harness.py`/`policy_gate.py`/`audit_envelope.py`
  (confirmado por `git diff` — intocados)
- sem motor real, cloud, subprocess, persistência
- sem policy/audit/vault reais
- sem alteração de `.github/`, `pyproject.toml`, `setup.cfg`
- sem tag, release ou PyPI

## 8. Validação final

| Item | Resultado |
|---|---|
| RUFF | PASS |
| PYTEST | PASS_886 (884 + 2 testes de help) |
| BUILD | PASS_IN_TMP_SANDBOX_FS_QUIRK |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | WARN (LOG_LEGACY_UNANCHORED, esperado) |
| COBERTURA | 86% (≥ 80%) |
| GIT_FSCK | PASS |
| `git diff --name-only HEAD -- .github pyproject.toml setup.cfg` | vazio (NO_FORBIDDEN_DIFF=true) |
| Módulos funcionais do Council | intocados (`git diff` vazio) |
| CI_STATUS | PASS |
| CI_JOBS | 17/17 |
| `git tag --points-at HEAD` | vazio (NO_NEW_TAG_ON_HEAD=true) |

## 9. Riscos remanescentes

- **Duplicação controlada** entre `cli_dry_run.py` e `chat_dry_run.py`
  permanece; a documentação agora a registra explicitamente e reserva a
  unificação para uma fase de refactor separada (MC20 SPEC → refactor), nunca
  junto com habilitação de execução real.
- Contagens de teste aparecem em vários lugares (README, relatórios); crescem
  a cada fase e são mantidas à mão — sem verificação automática de que o número
  do README bate com a suíte.
- O corpo do release no GitHub e o README são mantidos em sincronia
  manualmente; uma edição em um não atualiza o outro.

## 10. Próximo passo recomendado

MC20 — Shared Redaction/Output Helper SPEC: desenhar (sem refatorar ainda) uma
unificação segura do parsing/redação compartilhado entre CLI e Chat dry-run,
para depois executar um refactor isolado que não toque em nenhuma trava de
execução real.
