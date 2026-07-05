# MC28 — Consolidação local: saneamento do repo + commits MC24–MC27 (IL-100)

## 1. Status

```
STATUS_FINAL=PASS_MC28_LOCAL_CONSOLIDATION_READY
```

Entrega **local** completa. O push ao GitHub permanece gap **externo** já
documentado (403: conta autenticada sem permissão de escrita no repo
`Voltolini-SPACE/NOMOS` — ver `MC24_HANDOFF/MC24.1_PUSH_ATTEMPT.txt`).

## 2. Objetivo

Validar, remover ruído e consolidar em commits locais todo o trabalho pendente
do working tree (MC24 já commitado em bundle + MC25–MC27 + site), deixando o
repositório íntegro e pronto para push do operador.

## 3. Contexto de partida

- `main` local = `bbe2820` (= `origin/main`), com MC24–MC27 **não commitados**
  no working tree.
- `.git` com refs quebradas (`refs/heads/_probe` e afins, lixo de 0 bytes de
  sondagem anterior) que quebravam `fetch`/`push` e geravam warning no `git
  status`.
- `MC24_HANDOFF/mc24.bundle` continha os commits validados do MC24
  (`3bd5d04` + `f724dfe`, base `bbe2820`).

## 4. Ruído removido

| Item | Ação | Evidência |
|---|---|---|
| `.git/refs/heads/_probe`, `.git/objects/_probe`, `.git/_probe_write`, `.git/index.lock` (todos 0 bytes) | removidos | `git show-ref --heads` lista só `main`; `git fsck --no-dangling` limpo; sem warnings |
| `.DS_Store` (raiz do repo) | removido e adicionado ao `.gitignore` | `git check-ignore .DS_Store` passa a casar |

## 5. Aplicação do MC24 (paridade exata)

- `git bundle verify mc24.bundle` → ok; `git fetch` do bundle → `f724dfe`.
- `git reset --mixed f724dfe` (não toca no working tree).
- `git diff HEAD -- <arquivos dos patches MC24>` → **vazio** (working tree
  byte-a-byte igual aos commits validados).

## 6. Commits criados (base `bbe2820` → topo)

| Commit | Conteúdo |
|---|---|
| `3bd5d04` | feat(council): unify CLI/chat forbidden flags contract (MC24) — do bundle |
| `f724dfe` | docs(council): document MC24 forbidden flags reconciliation — do bundle |
| `eb997a6` | chore(repo): .gitignore (extração de sdist, .DS_Store) + conftest.py raiz |
| `841a81f` | feat(site): site NOMOS (brandbook congelado) + docs de instalação (MC25) |
| `0e80275` | feat(tools): update agent MC27.0 (check gate + diff proposer, apply fail-closed) + docs + 75 testes |
| (este) | docs(repo): CHANGELOG MC25–27 + este relatório |

Cada commit é autoconsistente (bisect-hygiene): `841a81f` validado em worktree
isolado (`15 passed` em `test_site_polish.py`, ruff limpo).

## 7. Comandos executados (evidência real)

| Comando | Retorno | Resultado |
|---|---:|---|
| `git show-ref --heads` (pós-saneamento) | 0 | só `refs/heads/main` |
| `git fsck --no-dangling` | 0 | sem erros |
| `git bundle verify mc24.bundle` | 0 | "is okay" |
| `python3 -m pytest -q tests/council tests/test_a* tests/test_c*` | 0 | 646 passed |
| `python3 -m pytest -q tests/test_[d-r]*.py` | 0 | 259 passed |
| `python3 -m pytest -q tests/test_[s-z]*.py` | 0 | 209 passed |
| **Total da suíte** (= coleta `--collect-only`: 1114) | — | **1114/1114 passed, 2×** (antes e depois dos commits) |
| `python3 -m ruff check .` (3× isolado) | 0 | All checks passed! |
| `python3 -m ruff check src tests` (paridade CI) | 0 | All checks passed! |
| `python3 -m compileall src tools` | 0 | OK |
| `tools/nomos_update_agent.py --version` | 0 | `MC27.0` |
| `tools/nomos_update_agent.py --check` | 0 | CONSISTENTE |
| `tools/nomos_update_agent.py --diff` | 0 | `PROPOSTA_DIFF_ONLY`, `NO_WRITE`, `HUMAN_APPROVAL_REQUIRED` |
| `tools/nomos_update_agent.py --apply` | 1 | bloqueado fail-closed (esperado) |
| `git status --short` (pós-commits) | 0 | vazio (working tree limpo) |

Nota: uma execução inicial de `ruff check .` acusou 14 erros **transitórios**
(concorrência com artefatos temporários de um pytest em background que o
sandbox matou); três execuções isoladas subsequentes retornaram limpas — o
código nunca teve os erros.

## 8. Fora de escopo (não alterado)

- Nenhuma mudança funcional em `src/` além do que já estava validado (MC24).
- Brandbook congelado commitado **como está** (conteúdo não editado).
- Sem tag, sem release, sem PyPI (proibições do handoff mantidas).
- `.github/` e `pyproject.toml` intocados nesta missão.

## 9. Gap conhecido (externo)

`KNOWN_GAPS=1 (externo)`: push bloqueado por permissão (403 — conta
`AIPantheon` sem escrita em `Voltolini-SPACE/NOMOS`). Opções A/B/C documentadas
em `MC24_HANDOFF/MC24.1_PUSH_ATTEMPT.txt`; bundle consolidado e script
atualizados em `MC24_HANDOFF/` (ver `00_LEIA_PRIMEIRO_MC28.txt`).

## 10. Veredito

Repositório saneado, trabalho MC24–MC27 + site consolidado em commits limpos e
autoconsistentes, suíte completa verde (1114), lint limpo, agente de update
íntegro e fail-closed. Falta apenas o push, que depende de credencial/permissão
do operador.
