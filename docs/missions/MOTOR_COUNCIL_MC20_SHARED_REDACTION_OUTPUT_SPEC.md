# MOTOR COUNCIL MC20 — SHARED REDACTION/OUTPUT HELPER SPEC

## 1. Status final

STATUS_FINAL=PASS_MOTOR_COUNCIL_MC20_SHARED_REDACTION_OUTPUT_SPEC

Especificação técnica de um futuro helper compartilhado de saída/redação para
o Motor Council dry-run criada em
`docs/architecture/MOTOR_COUNCIL_SHARED_OUTPUT_REDACTION_SPEC_v1.md` (20
seções), documentando exatamente a duplicação controlada entre
`cli_dry_run.py` (MC15) e `chat_dry_run.py` (MC18) e como unificá-la com
segurança numa fase futura (MC21+). Missão SPEC-only: nenhum helper
implementado, nenhum refactor, nenhum código/teste/workflow alterado. Suíte
segue em 886. Nenhuma tag/release/PyPI.

## 2. Baseline

| Item | Resultado |
|---|---|
| BASELINE_HEAD | 1e2cd0e |
| BASELINE_TAG | v1.3.0rc4-motor-council-dry-run-17-g1e2cd0e |
| GIT_STATUS | CLEAN (antes das mudanças) |
| GIT_FSCK | PASS (1 commit dangling pré-existente, benigno) |
| RUFF | PASS |
| PYTEST | PASS_886 |
| BUILD | PASS_IN_TMP_SANDBOX_FS_QUIRK |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | WARN (LOG_LEGACY_UNANCHORED, esperado) |

## 3. Escopo

```text
SPEC_ONLY=true
HELPER_IMPLEMENTED=false
RUNTIME_CHANGED=false
TESTS_CHANGED=false
REAL_ENGINE_EXECUTION=false
REAL_POLICY=false
REAL_AUDIT=false
REAL_VAULT=false
PERSISTENCE=false
```

## 4. Documentos criados/atualizados

| Arquivo | Status |
|---|---|
| `docs/architecture/MOTOR_COUNCIL_SHARED_OUTPUT_REDACTION_SPEC_v1.md` | criado (20 seções) |
| `docs/architecture/MOTOR_COUNCIL_INDEX_v1.md` | atualizado — flags `MC20_SHARED_REDACTION_OUTPUT_SPEC=PASS`, `SHARED_HELPER_IMPLEMENTED=false`, `CLI_CHAT_DUPLICATION=KNOWN_CONTROLLED` + ponteiro |
| `docs/architecture/MOTOR_COUNCIL_UX_SPEC_v1.md` | atualizado — ponteiro para a nova spec |
| `docs/architecture/MOTOR_COUNCIL_CHAT_DRY_RUN_SPEC_v1.md` | atualizado — ponteiro para a nova spec |
| `docs/missions/MOTOR_COUNCIL_MC20_SHARED_REDACTION_OUTPUT_SPEC.md` | criado (este relatório) |
| `CHANGELOG.md` | atualizado — entrada `[Unreleased]` (Documentation / Not changed) |

## 5. O que foi especificado

- **Estado atual da duplicação** com tabela lado a lado de `cli_dry_run.py` vs.
  `chat_dry_run.py`: entrada (tokens vs. string), saída (imprime+int vs.
  retorna str), prefixos distintos, mesmo contrato escalar de JSON, mesmos
  invariantes de segurança.
- **Achado concreto**: o conjunto de flags proibidas da CLI tem **8** flags e
  o do chat tem **10** (o chat adiciona `--vault-real`/`--engine-real`). É uma
  inconsistência de contrato real (não abre execução real, pois flag
  desconhecida já é fail-closed) que o helper unificado deve reconciliar — não
  corrigida aqui (SPEC-only), registrada para o refactor (MC24).
- **Invariantes de segurança compartilhadas**, **dados proibidos** (16 itens,
  incl. `trace`/`audit_envelope`/`repr(result)`/`result.to_dict()`) e **campos
  escalares permitidos** (os 8 atuais + os propostos `interface`/`mode`
  normalizado).
- **Contratos de saída** humano, JSON, gate-blocked, exceção e modo privado,
  parametrizados por `interface="cli|chat"`.
- **APIs proibidas** (`to_dict`/`repr`/`vars`/`asdict`/dump do resultado) e as
  proibições padrão do Council (FS/env/tempo/random/rede/subprocess/cloud/
  harness/kernel real).
- **Esboço de API futura** (`CouncilSafeOutput` frozen dataclass +
  `build_safe_output`/`render_human_output`/`render_json_output`/
  `render_denied_output`/`render_gate_blocked_output`), marcado
  `API_SKETCH_ONLY=true`.
- **Plano de migração** MC21 (implementar helper) → MC22 (migrar CLI) → MC23
  (migrar chat) → MC24 (hardening + reconciliar flags 8↔10), cada fase com CI
  e testes próprios e sem habilitar execução real.
- **Plano de testes futuros** (9 nomes) e **failure modes** (6 códigos
  `SHARED_*`, todos "impossíveis por construção").

## 6. O que NÃO foi feito

- sem helper implementado
- sem refactor de `cli_dry_run.py`/`chat_dry_run.py`
- sem runtime novo
- sem motor real
- sem cloud/rede/subprocess
- sem persistência
- sem policy/audit/vault reais
- sem alteração de `src/`, `tests/`, `.github/`, `pyproject.toml`, `setup.cfg`
- sem tag
- sem release
- sem PyPI

## 7. Validação final

| Item | Resultado |
|---|---|
| RUFF | PASS |
| PYTEST | PASS_886 (inalterado) |
| BUILD | PASS_IN_TMP_SANDBOX_FS_QUIRK |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | WARN (LOG_LEGACY_UNANCHORED, esperado) |
| GIT_FSCK | PASS |
| `git diff --name-only HEAD -- src tests .github pyproject.toml setup.cfg` | vazio (NO_CODE_TEST_WORKFLOW_DIFF=true) |
| CI_STATUS | PASS |
| CI_JOBS | 17/17 |
| `git tag --points-at HEAD` | vazio (NO_NEW_TAG_ON_HEAD=true) |

## 8. Riscos remanescentes

- A spec é normativa, mas não vinculante por código — a implementação MC21
  deve revisá-la antes de qualquer código, pela disciplina
  `implementation-loop-100`.
- A decisão de **adicionar** `interface`/`mode` ao JSON público (vs. manter os
  8 escalares atuais) foi deixada em aberto na spec como escolha explícita da
  migração; adicioná-los é uma mudança de contrato público que precisa de
  testes e nota de CHANGELOG na fase que a fizer.
- A divergência das flags proibidas (8 na CLI, 10 no chat) permanece no código
  até MC24; documentada, mas não corrigida.

## 9. Próximo passo recomendado

MC21 — Shared Redaction Helper Implementation: criar o módulo helper real
(`CouncilSafeOutput` + `build_/render_*`) com seus próprios testes de
segurança/AST, **sem** migrar CLI/Chat ainda (as duas superfícies seguem com
seu código atual até MC22/MC23).
