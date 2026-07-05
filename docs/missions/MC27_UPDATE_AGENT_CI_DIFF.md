# MC27 — CI Read-Only Gate + Diff Proposer para NOMOS Update Agent

## 1. Status

```
STATUS_FINAL=PASS_MC27_UPDATE_AGENT_CI_DIFF_READY
```

## 2. Resumo do que foi implementado

O `tools/nomos_update_agent.py` foi promovido para **MC27.0** com dois avanços controlados,
ambos **read-only / proposal-only**:

1. **Gate CI read-only** — `--check --json` agora emite, além dos campos MC26, um bloco
   estável para CI: `agent_version`, `mode`, `consistent`, `checks_total`, `checks_passed`,
   `checks_failed`, `human_approval_required`, `real_execution_enabled` (false),
   `auto_push_enabled` (false), `diff_proposer_available` (true). Exit 0 = consistente,
   exit 1 = inconsistente -> serve como gate de pipeline sem escrever nada.
2. **Modo `--diff` proposal-only** — propõe patches de documentação/consistência
   (ex.: links faltando no README). Imprime `PROPOSTA_DIFF_ONLY`, `NO_WRITE`,
   `HUMAN_APPROVAL_REQUIRED`. `--diff --json` emite `{agent_version, mode, proposal_only,
   writes_enabled:false, human_approval_required, patches[]}`. **Nunca escreve, nunca
   executa git.**

`--apply` permanece **bloqueado/fail-closed** em todas as variações.

## 3. HEAD

- HEAD inicial e final: `bbe2820` (`bbe282061801ac82dd309cee0e553feefe4a69fa`) — nenhum commit.
- Branch: `main`.

## 4. Arquivos alterados/criados

| Arquivo | Ação |
|---|---|
| `tools/nomos_update_agent.py` | Reescrito: MC27.0, campos de gate, `--diff`/`--diff --json` |
| `tests/test_mc27_update_agent_diff.py` | CRIADO — 17 testes reais (cobrem os 18 casos exigidos) |
| `tests/test_mc26_update_agent_check.py` | Ajuste mínimo: 2 asserções de versão agora **dinâmicas** (usam `AGENT_VERSION`) para não travar em bump |
| `docs/governance/NOMOS_UPDATE_AGENT.md` | Atualizado para MC27.0 (gate + `--diff`) |
| `docs/missions/MC27_UPDATE_AGENT_CI_DIFF.md` | Este relatório |

Pré-existentes no working tree (NÃO desta missão): `CHANGELOG.md`, `docs/architecture/*`,
`src/nomos/council/chat_dry_run.py`, `cli_dry_run.py` (modificados antes do MC26).

## 5. Comandos executados (evidência real)

| Comando | Exit | Resultado |
|---|---:|---|
| `git rev-parse --short HEAD` | 0 | `bbe2820` (sem commit) |
| `--version` | 0 | `MC27.0` |
| `--check` | 0 | `CONSISTENTE` (8 checks) |
| `--check --json \| python -m json.tool` | 0 | JSON válido com 10 campos MC27 |
| `--diff` | 0 | 3→2 patches, marcadores presentes |
| `--diff --json \| python -m json.tool` | 0 | JSON válido, `proposal_only=true`, `writes_enabled=false` |
| `--apply` | 1 | bloqueado (informa desabilitado) |
| `--apply --i-understand-this-is-disabled` | 1 | bloqueado |
| `--apply --i-understand-this-writes-files` | 1 | fail-closed, nenhuma escrita |
| `pytest test_mc25_deliverables + mc26 + mc27 -q` | 0 | **75 passed** |
| `pytest -q` (bare) | 0 | **1099 passed** |
| `ruff check .` | 0 | All checks passed! |
| `grep subprocess\|os.system\|Popen\|twine tools/...` | 1 | nenhuma ocorrência (limpo) |
| `git diff -- .github pyproject.toml setup.cfg` | 0 | vazio (intactos) |
| md5(git status) antes==depois de `--diff` | — | idêntico (não escreve) |

> Nota: a missão citou `tests/test_mc25_update_agent.py`; o arquivo real é
> `tests/test_mc25_deliverables.py` (usado nos comandos acima).

## 6. Resultados dos testes

- `tests/test_mc27_update_agent_diff.py`: **17 passed** (cobrem os 18 requisitos: version,
  check, check --json, campos MC27, diff exit0, marcadores, diff --json, proposal_only,
  writes_enabled, patches seguros, apply bloqueado, sem primitivas, sem mutação, fail-closed).
- `tests/test_mc26_update_agent_check.py`: **13 passed** (asserções de versão tornadas dinâmicas).
- `tests/test_mc25_deliverables.py`: **45 passed** (preservado).
- Suíte ampla `pytest -q`: **1099 passed**, 0 falhas, 0 erros.
- `ruff check .`: **All checks passed!**

## 7. Evidência de que não houve execução real

- `grep -REn "subprocess|os.system|Popen|twine" tools/nomos_update_agent.py` → **0 ocorrências**.
- Estado do git é lido por parsing direto de `.git/HEAD` (somente leitura), sem processos.
- Teste `test_agente_sem_primitivas_de_execucao` verifica a ausência dos tokens.

## 8. Evidência de que --apply segue bloqueado

- `--apply` → exit 1, mensagem "aplicação automática continua desabilitada".
- `--apply --i-understand-this-is-disabled` → exit 1.
- `--apply --i-understand-this-writes-files` → exit 1, "fail-closed, nenhuma escrita".
- Teste `test_apply_bloqueado` cobre as três variações.

## 9. Evidência de arquivos proibidos intactos

- `git diff -- .github pyproject.toml setup.cfg` → **saída vazia** (exit 0).
- `setup.cfg` não existe e não foi criado.

## 10. Evidência de segurança

```
LOCAL_FIRST=YES
NO_SECRET_LEAK=YES            (--check secrets: nenhum; patches sem tokens)
NO_REAL_EXECUTION=YES         (0 primitivas; git lido de .git)
NO_AUTO_PUSH=YES
NO_TAG=YES
NO_RELEASE=YES
NO_PYPI=YES
HUMAN_APPROVAL_REQUIRED=YES   (--diff proposal-only; --apply bloqueado)
ZERO_WRITE_ON_DIFF=YES        (md5 git status idêntico antes/depois)
```

## 11. Limitações honestas (KNOWN_GAPS)

- `--diff` é heurístico e conservador: hoje detecta links de doc faltando no README e
  versão desatualizada na governança. Não detecta divergências semânticas profundas.
- `--diff` **não** gera arquivo `.patch` ainda (isso é a MC28); apenas descreve a proposta.
- `--apply` continua não implementado por design (approval-first).
- O gate CI está **documentado e pronto**, mas nenhum workflow em `.github/` foi criado
  (proibido nesta missão). A integração real de pipeline fica para uma missão futura.
- Mudanças pré-existentes no working tree (council/*.py, CHANGELOG) não são desta missão.
- Deliverables seguem untracked; commit/push é ação humana.

## 12. Critério de 100%

```
SPEC_DECLARED=TRUE
SCOPE_RESPECTED=TRUE
IMPLEMENTATION_DONE=TRUE
TESTS_EXECUTED=TRUE
TESTS_PASSING=TRUE   (MC25 45 + MC26 13 + MC27 17; suíte 1099)
VALIDATION_EXECUTED=TRUE
REGRESSION_CHECKED=TRUE
KNOWN_GAPS=DOCUMENTED_NON_BLOCKING
EVIDENCE_RECORDED=TRUE
STATUS_FINAL=PASS_MC27_UPDATE_AGENT_CI_DIFF_READY
```

## 13. Recomendação da MC28

**MC28 — Approval Envelope para geração de patch exportável (ainda sem aplicação):**
`--diff --write-proposal <caminho>.patch` que grava a proposta como arquivo `.patch`
acompanhado de **hash SHA256** e **nonce de aprovação humana**, registrados num envelope.
Restrições mantidas: **sem** `git apply`, **sem** commit, **sem** push, **sem** tag/release.
A gravação do arquivo de proposta deve exigir flag explícita e continuar não aplicando nada.
