# MC26 — NOMOS Update Agent Hardening + CI-Safe Check Mode

## 1. Status

```
STATUS_FINAL=PASS_MC26_UPDATE_AGENT_CHECK_MODE_READY
```

## 2. Objetivo

Evoluir o scaffold de `tools/nomos_update_agent.py` para um verificador real de
consistência com `--check`, `--version` e saída estruturada `--json`, pronto para CI,
sem push/tag/release/PyPI e sem execução destrutiva. Aplicado sob a skill
`implementation-loop-100` (SPEC -> IMPLEMENTAR -> TESTAR -> VALIDAR -> APRIMORAR ->
RE-TESTAR -> EVIDENCIAR -> ENTREGAR).

## 3. HEAD

- HEAD inicial e final: `bbe282061801ac82dd309cee0e553feefe4a69fa` (nenhum commit criado).
- Branch: `main`.

## 4. Arquivos alterados/criados nesta missão

| Arquivo | Ação | Observação |
|---|---|---|
| `tools/nomos_update_agent.py` | REESCRITO | --check/--version/--json reais; sem primitivas de execução |
| `tests/test_mc26_update_agent_check.py` | CRIADO | 13 testes reais |
| `conftest.py` (raiz) | CRIADO | `collect_ignore_glob=["nomos-[0-9]*"]` resolve conflito de coleção |
| `.gitignore` | +2 linhas | ignora artefato de build `nomos-[0-9]*/` (padrão compatível já existia) |

Pré-existentes (NÃO alterados por esta missão — já modificados no working tree antes do
MC26, confirmado no `git status` da inspeção): `CHANGELOG.md`,
`docs/architecture/MOTOR_COUNCIL_INDEX_v1.md`,
`docs/architecture/MOTOR_COUNCIL_SHARED_OUTPUT_REDACTION_SPEC_v1.md`,
`docs/missions/MOTOR_COUNCIL_MC23_CHAT_MIGRATION_SAFE_OUTPUT.md`,
`src/nomos/council/chat_dry_run.py`, `src/nomos/council/cli_dry_run.py`.

## 5. Arquivos preservados / congelados

| Alvo | Prova |
|---|---|
| `.github/` | `git diff --stat .github/` -> vazio |
| `pyproject.toml` | `git diff --stat pyproject.toml` -> vazio |
| `setup.cfg` | inexistente; não criado |
| `src/nomos/**` | nenhuma edição desta missão (mudanças em council são pré-existentes) |
| `nomos-1.3.0rc16/` | preservado em disco (NÃO deletado); apenas gitignored |

## 6. Comandos executados (evidência real)

| # | Comando | Retorno/Exit | Resultado |
|---|---|---:|---|
| 1 | `git status --short` | 0 | árvore listada; artefato já não aparece (gitignored) |
| 2 | `python tools/nomos_update_agent.py --version` | 0 | imprime `MC26.0` |
| 3 | `python tools/nomos_update_agent.py --check` | 0 | 8 checks OK, `CONSISTENTE` |
| 4 | `... --check --json` | 0 | JSON com todos os campos exigidos |
| 5 | `... --check --json \| python -m json.tool` | 0 | JSON válido (parseado) |
| 6 | `... --apply` | 1 | bloqueado (requer flag) |
| 7 | `... --apply --i-understand-this-writes-files` | 1 | fail-closed, nenhuma escrita |
| 8 | `pytest tests/test_mc26_update_agent_check.py` | 0 | 13 passed |
| 9 | `ruff check tools/... tests/... conftest.py` | 0 | All checks passed! |
| 10 | `pytest` (bare, sem --ignore) | 0 | 1082 passed (conftest resolveu coleção) |
| 11 | `git diff --stat .github/ pyproject.toml` | 0 | vazio (intactos) |
| 12 | `grep -cE "subprocess\|os.system\|Popen\|check_output\|twine"` | 0 | agente sem primitivas de execução |

Durante o loop houve DUAS falhas reais capturadas e corrigidas (ver seção 8).

## 7. Testes e validações

| Validação | Evidência | Resultado |
|---|---|---|
| `--version` imprime MC26.0 | subprocess real | PASS |
| `--check` exit 0 em repo consistente | subprocess real | PASS |
| `--check` menciona brand/manual/landing/links/secrets/git | stdout | PASS |
| `--check --json` parseável (json.loads) e completo | teste | PASS |
| JSON contém status/version/checks/errors/warnings/files_checked/git/safe_mode/timestamp_utc/next_recommendation | teste | PASS |
| JSON sem códigos ANSI | teste | PASS |
| Agente sem subprocess/os.system/twine | teste substring | PASS |
| Agente sem popen/check_output | teste substring | PASS |
| `--apply` bloqueado sem flag (exit 1) | subprocess | PASS |
| `--apply` fail-closed com flag (exit 1, sem escrita) | subprocess | PASS |
| Links internos da landing resolvem | módulo | PASS |
| Fail-closed com deliverable ausente (fixture temp) | tmp_path | PASS |
| Exit code 1 quando inconsistente | módulo | PASS |
| `--check` não muta o repositório (hash antes==depois) | subprocess+hash | PASS |
| Suíte ampla (anti-regressão) | 1082 passed | PASS |
| Lint global (src tests tools) | ruff exit 0 | PASS |

## 8. Correções feitas durante o loop

1. **Falha real #1 — token "subprocess"/"twine" no código.** O docstring/help do agente
   continha as palavras `subprocess`, `os.system` e `twine` em prosa, disparando os
   testes de substring (MC26 e também MC25). Corrigido reescrevendo a prosa para
   "não executa processos externos", removendo os tokens literais. Re-teste: 13 passed
   e MC25 45 passed.
2. **Falha real #2 — `import pytest` não usado.** `ruff` acusou F401 no novo teste.
   Removido o import (fixture `tmp_path` é automática). Re-check ruff: All checks passed.

## 9. Anti-regressão

- `pytest` (bare): **1082 passed** — o novo `conftest.py` (raiz) com
  `collect_ignore_glob=["nomos-[0-9]*"]` resolveu **permanentemente** o conflito de
  coleção causado pelo artefato `nomos-1.3.0rc16/`, eliminando a necessidade de `--ignore`.
- Testes MC25 (`test_mc25_deliverables.py`): 45 passed — a reescrita do agente preservou
  todas as invariantes de segurança que o MC25 verifica.
- `.github/`, `pyproject.toml`: diff vazio.

## 10. Gaps conhecidos

```
KNOWN_GAPS:
- --apply permanece intencionalmente NÃO implementado (fail-closed, approval-first).
  Escrita real de arquivos fica para missão futura, sempre sob aprovação humana.
- Artefato nomos-1.3.0rc16/ preservado em disco por precaução (não deletado sem
  aprovação humana explícita); já gitignored e ignorado na coleção do pytest.
- Mudanças pré-existentes no working tree (CHANGELOG, council/*.py) não são desta
  missão e permanecem sem commit — decisão humana.
- Deliverables MC25/MC26 seguem untracked; commit/push é ação humana.
```

## 11. Critérios de aceite

| Critério | Status | Evidência |
|---|---|---|
| `--version` funciona | PASS | imprime MC26.0, exit 0 |
| `--check` funciona | PASS | 8 checks, exit 0 |
| `--check --json` gera JSON válido | PASS | json.tool exit 0 |
| testes novos passam | PASS | 13 passed |
| lint passa | PASS | ruff exit 0 |
| suíte ampla passa | PASS | 1082 passed (sem --ignore) |
| nenhum arquivo proibido alterado | PASS | diff .github/pyproject vazio |
| nenhuma execução destrutiva adicionada | PASS | 0 primitivas de processo |
| agente incapaz de push/tag/release/deploy | PASS | grep=0; sem subprocess |
| relatório com evidência real | PASS | este documento |

## 12. Evidência de segurança

```
LOCAL_FIRST=YES
NO_SECRET_LEAK=YES            (scan --check: nenhum segredo aparente)
NO_REAL_EXECUTION=YES         (0 primitivas de execução; dry-run)
NO_AUTO_PUSH=YES             (agente sem subprocess -> incapaz de git)
NO_TAG=YES
NO_RELEASE=YES
NO_PYPI=YES                  (sem twine; nada publicado)
HUMAN_APPROVAL_REQUIRED=YES  (--apply fail-closed; commit/push humanos)
FAIL_CLOSED_ON_UNCERTAINTY=YES (deliverable ausente -> status inconsistent, exit 1)
```

## 13. Critério de 100%

```
SPEC_DECLARED=TRUE
SCOPE_RESPECTED=TRUE
IMPLEMENTATION_DONE=TRUE
TESTS_EXECUTED=TRUE
TESTS_PASSING=TRUE
VALIDATION_EXECUTED=TRUE
REGRESSION_CHECKED=TRUE
KNOWN_GAPS=DOCUMENTED_NON_BLOCKING
ROLLBACK_OR_BACKUP_READY=TRUE (arquivos novos untracked; .gitignore/conftest reversíveis)
EVIDENCE_RECORDED=TRUE
STATUS_FINAL=PASS_MC26_UPDATE_AGENT_CHECK_MODE_READY
```

## 14. Veredito

O NOMOS Update Agent passou de scaffold para verificador real CI-safe: `--check` roda 8
verificações (existência, seções, links, secrets, git), `--version` imprime `MC26.0`,
`--json` emite relatório determinístico com todos os campos. 13 testes novos + 1082 na
suíte ampla passam com evidência executada; duas falhas reais foram corrigidas no loop.
O agente é **incapaz de executar processos** (sem subprocess/os.system), portanto não faz
push/tag/release/deploy. O conflito do artefato foi resolvido de forma permanente e
não-destrutiva (gitignore + conftest, sem deletar dados).

**STATUS_FINAL=PASS_MC26_UPDATE_AGENT_CHECK_MODE_READY**

## 15. Próxima missão recomendada

**MC27 — Update Agent CI Integration (read-only) + `--diff` proposto.** Adicionar workflow
CI que roda `--check --json` como gate (sem escrever), publica o relatório como artifact do
job, e um modo `--diff` que **propõe** patches de sincronização (README <-> Brandbook <->
Manual <-> Landing) sem aplicá-los — mantendo approval-first e sem push automático.
