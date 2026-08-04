# H4.6 — Promoção local e publicação verificável do 1.3.0rc18

```text
STATUS_FINAL=H4_6_LOCAL_PASS_REMOTE_BLOCKED
BASELINE_HEAD=fe80e04418b0d3e138c7d4e13d4fbc89da8ecf26
FINAL_HEAD=cd1964a02c847753bebf5d830c53294be9001b02
VERSION_INITIAL=1.3.0rc17
VERSION_FINAL=1.3.0rc18
COMMITS_CREATED=2 (3733e1b chore bump, cd1964a docs release notes)
TAG_CREATED=v1.3.0rc18 (local apenas)
TAG_SHA=cd1964a02c847753bebf5d830c53294be9001b02
TESTS_PASSED=1973
TESTS_FAILED=0
MYPY_ERRORS=0
RUFF_ERRORS=0
COVERAGE_GENERAL=84.92_PERCENT
COVERAGE_DIRECTED=95.45_PERCENT
BOUNDARY_GATE=PASS
POLICY_FAIL_CLOSED=PASS
AGENT_REPAIR_FORENSIC_SAFE=PASS
WHEEL_FILE=nomos-1.3.0rc18-py3-none-any.whl
WHEEL_SHA256=91047027cc07520e1ee387653defec931c1103b781e57c40cbbbfe1fba79766c
WHEEL_SMOKE=PASS
ROLLBACK_TEST=PASS (rc18 -> uninstall -> rc17 real artifact -> verify -> reinstall rc18 -> verify)
SITE_DOC_CONSISTENCY=13_OF_13
WORKTREE_STATUS=CONTROLADO
BRANCH_PUSH=BLOCKED
TAG_PUSH=BLOCKED
REMOTE_SHA_VERIFIED=FAIL (local cd1964a != remote 845eda6; tag ausente no remoto)
REMOTE_CI=UNVERIFIED (nada foi publicado; nenhum workflow foi disparado)
PRODUCTION_MUTATED=NO
NEXT_RECOMMENDED_STEP=usuário publica branch + tag com credencial válida (git local ou GitHub Desktop já aberto); depois confirmar o run de `release.yml` (dispara em push de tag `v*`) antes de qualquer promoção para 1.3.0 estável
```

## 1. Baseline

Revalidado exatamente como declarado pela missão antes de qualquer
edição:

```
git status --short   -> só os 2 untracked pré-existentes (H4.0)
git branch --show-current -> loop/fase3-agent-boundary-wiring
git rev-parse HEAD    -> fe80e04418b0d3e138c7d4e13d4fbc89da8ecf26
```

Os 3 commits H4.5 exigidos (`c665330`, `13da85a`, `fe80e04`) foram
confirmados presentes e íntegros via `git show --stat --oneline` — sem
divergência de baseline.

**Gate remoto inicial:** `git fetch origin` + comparação de SHAs mostrou
`origin/loop/fase3-agent-boundary-wiring` ainda em `845eda6` — os 3
commits H4.5 permaneciam ausentes do remoto no início desta missão
(confirma o estado já registrado no relatório H4.5: o usuário publicou
externamente até `845eda6`, mas não os 3 commits seguintes). Tentativa
de `git push` reproduziu o mesmo erro de credencial de todas as missões
anteriores:
`fatal: could not read Password for 'https://Voltolini-SPACE@github.com': No such device or address`.
`REMOTE_PUSH=BLOCKED_BY_CREDENTIALS_OR_OS_AUTHORIZATION` registrado;
prosseguiu-se com os gates locais.

## 2. Arquivos de versão alterados

Inventário prévio (`rg -n '1\.3\.0rc17|__version__|version\s*=|VERSION' pyproject.toml setup.cfg setup.py src tests docs site scripts`)
identificou a fonte canônica real, confirmada por leitura de
`tools/nomos_update_agent.py::_check_versao_coerente` (o único gate real
do projeto que verifica coerência de versão): **apenas 2 arquivos** são
checados — `pyproject.toml` (`version =`) e `src/nomos/__init__.py`
(`__version__ =`). Ambos são a fonte de verdade; CLI e wheel herdam
automaticamente (não há geração/derivação separada a rodar).

Alterados:
- `pyproject.toml` — `version = "1.3.0rc17"` → `"1.3.0rc18"`.
- `src/nomos/__init__.py` — `__version__ = "1.3.0rc17"` → `"1.3.0rc18"`.
- `README.md` — 2 menções genéricas de "versão atual"/"release
  candidate" (texto solto, não mecanismo derivado).
- `CHANGELOG.md` — cabeçalho `## [Unreleased]` (938 linhas acumuladas
  desde o corte de `1.3.0rc17` em 2026-07-05) virou
  `## [1.3.0rc18] — 2026-08-04 (...)`, com um novo `## [Unreleased]`
  vazio acima — mesmo padrão já usado pelo próprio arquivo para
  rc4..rc17. Só o cabeçalho foi trocado; nenhum bullet de conteúdo foi
  reescrito.

**Deliberadamente NÃO alterado:** `site/index.html`. Seus 4 links de
download apontam para a tag `v1.3.0rc17-cockpit-conexoes` — a **última
release realmente publicada**, com assets de verdade no GitHub Releases
— não para a versão interna de `pyproject.toml`. `docs/missions/
MC43_RELEASE_PREP.md` (o documento que criou essa tag) documenta
explicitamente que o site só é atualizado **depois** que a tag é
publicada de fato, para nunca apontar para um asset inexistente (404).
`tests/test_site_downloads.py` só verifica consistência **interna** dos
links (mesma tag nos 3 botões), não contra `pyproject.toml` — confirmado
passando sem nenhuma alteração no site. Atualizar os links agora,
com `v1.3.0rc18` ainda não publicado, quebraria os downloads reais do
site.

## 3. Commits

| Commit | Tipo | Conteúdo |
|---|---|---|
| `3733e1b` | `chore(nomos)` | bump para 1.3.0rc18 (4 arquivos: pyproject.toml, __init__.py, README.md, CHANGELOG.md) |
| `cd1964a` | `docs(nomos)` | release notes de 1.3.0rc18 (`docs/missions/RELEASE_NOTES_v1.3.0rc18.md`) |

Mais a tag anotada local `v1.3.0rc18` (aponta para `cd1964a`, não para
`fe80e04`).

## 4. Comandos e resultados

```
COMANDO: mypy src/nomos --ignore-missing-imports
RESULTADO: Success: no issues found in 112 source files

COMANDO: ruff check src tests examples
RESULTADO: All checks passed!

COMANDO: pytest -q tests/test_h4_5_a_*.py tests/test_h4_5_b_*.py tests/test_h4_5_c_*.py tests/test_h4_5_d_*.py tests/test_missao_validacao_anti_regressao.py tests/test_site_downloads.py
RESULTADO: 76 passed

COMANDO: pytest -q -n4  (suíte completa)
RESULTADO: 1973 passed, 0 failed (idêntico ao baseline — bump de versão não introduziu regressão)

COMANDO: pytest -q -n4 --cov=nomos --cov-report=term --cov-fail-under=80
RESULTADO: TOTAL 84.92% (gate >=80%)

COMANDO: pytest -q --cov=nomos.kernel.evidencia --cov=nomos.ext.skill_catalogo --cov-report=term --cov-fail-under=90 tests/test_evidencia_pacote.py tests/test_mc29_skills_catalogo.py tests/test_mc29_painel.py tests/test_mc30_onda_a.py
RESULTADO: TOTAL 95.45% (gate >=90%)

COMANDO: rm -rf build dist && python -m build --wheel
RESULTADO: Successfully built nomos-1.3.0rc18-py3-none-any.whl

COMANDO: pip install (venv limpa) dist/nomos-1.3.0rc18-py3-none-any.whl
RESULTADO: instalado sem erro

COMANDO: nomos --version
RESULTADO: nomos 1.3.0rc18

COMANDO: python -c "import nomos; print(nomos.__version__)"
RESULTADO: 1.3.0rc18

COMANDO: python -m zipfile -l dist/*.whl  +  leitura de METADATA (stdlib zipfile)
RESULTADO: Version: 1.3.0rc18 (confirmado no METADATA do wheel)

COMANDO: nomos init && nomos status && nomos doutor  (venv limpa)
RESULTADO: rc=0 em todos; "NOMOS 1.3.0rc18" em toda saída; STATUS GERAL: PRONTO

COMANDO: python tools/nomos_update_agent.py --check --json
RESULTADO: checks_passed=13/13, consistent=true, git.head=cd1964a...
```

## 5. Artefatos e hashes

```
WHEEL_FILE=nomos-1.3.0rc18-py3-none-any.whl
WHEEL_SHA256=91047027cc07520e1ee387653defec931c1103b781e57c40cbbbfe1fba79766c
SDIST=não gerado (a missão só exigiu wheel build; nenhum `python -m build --sdist` foi pedido)
ARTIFACT_HASH_RECORDED=YES
REPRODUCIBLE_BUILD_PROVEN=NO
```

Só um build foi executado — por instrução explícita da missão, não se
afirma reprodutibilidade bit-a-bit sem dois builds independentes
comparados. `REPRODUCIBLE_BUILD_PROVEN=NO` é o estado honesto.

## 6. Tag

```
git tag --list v1.3.0rc18                          -> vazio antes de criar
git ls-remote --tags origin refs/tags/v1.3.0rc18    -> vazio antes de criar
git tag -a v1.3.0rc18 -m "NOMOS 1.3.0rc18"          -> criada
git rev-list -n 1 v1.3.0rc18                        -> cd1964a02c847753bebf5d830c53294be9001b02
git rev-parse HEAD                                  -> cd1964a02c847753bebf5d830c53294be9001b02
```

SHAs idênticos — a tag aponta para o commit final de release
(`cd1964a`, o commit das release notes), não para o `fe80e04` herdado do
H4.5.

## 7. Publicação

```
git push origin loop/fase3-agent-boundary-wiring
  -> fatal: could not read Password for 'https://Voltolini-SPACE@github.com': No such device or address

git push origin v1.3.0rc18
  -> fatal: could not read Password for 'https://Voltolini-SPACE@github.com': No such device or address
```

Verificação pós-tentativa (não confiando só na saída do push):

```
git fetch origin --tags
git rev-parse origin/loop/fase3-agent-boundary-wiring -> 845eda613fe7a400b2a1ced3d3081e200c5bea60
git ls-remote origin refs/heads/loop/fase3-agent-boundary-wiring -> 845eda6... (inalterado)
git ls-remote origin refs/tags/v1.3.0rc18                        -> (vazio — tag não existe no remoto)
```

```
BRANCH_PUSH=BLOCKED
TAG_PUSH=BLOCKED
REMOTE_RELEASE=BLOCKED
```

Tentativa adicional nesta sessão: usei o GitHub Desktop já aberto do
usuário (autorização concedida explicitamente) via automação de
computador para tentar clicar "Push origin" — um diálogo do sistema
fora da allowlist de apps concedida bloqueou o clique sem ficar visível
para inspeção (mesmo bloqueio já registrado no relatório H4.5). Não
insisti nessa via automatizada por uma segunda vez nesta missão; o botão
segue visível e pronto no GitHub Desktop do usuário.

## 8. CI remoto

`.github/workflows/release.yml` dispara em `push: tags: ["v*"]` —
seria o workflow relevante para a tag `v1.3.0rc18`.
`.github/workflows/ci.yml` dispara só em `push: branches: [main,
master]` — não dispararia nem para o push desta branch de trabalho.

Como nem a branch nem a tag chegaram ao remoto, **nenhum workflow foi
disparado** — não há run para acompanhar.

```
REMOTE_CI=UNVERIFIED
```

Não promovido para versão estável nesta condição, por instrução
explícita da missão.

## 9. Rollback

Executado na mesma venv limpa de smoke, artefato rc17 real disponível
(gerado nesta mesma sessão de trabalho, na validação de fechamento de
H4.5):

```
1. nomos --version                  -> nomos 1.3.0rc18
2. pip uninstall -y nomos           -> desinstalado; comando `nomos` some do PATH da venv
3. pip install nomos-1.3.0rc17-*.whl (artefato real, não fabricado)
4. nomos --version                  -> nomos 1.3.0rc17
   python -c "import nomos; print(nomos.__version__)" -> 1.3.0rc17
5. pip install --force-reinstall nomos-1.3.0rc18-*.whl
6. nomos --version                  -> nomos 1.3.0rc18
   python -c "import nomos; print(nomos.__version__)" -> 1.3.0rc18
```

```
ROLLBACK_TO_RC17=PASS (artefato real disponível e usado)
RC18_UNINSTALL_REINSTALL=PASS
```

Nenhuma produção foi alterada — tudo rodou numa venv temporária isolada
(`/tmp/nomos_rc18_venv`) e num `NOMOS_HOME` temporário separado.

## 10. Gaps residuais

1. **Publicação bloqueada** — mesma causa raiz de todas as missões
   anteriores desta série (credencial git ausente no sandbox); GitHub
   Desktop do usuário está aberto e pronto, mas um diálogo de sistema
   impediu o clique automatizado. Ação: usuário publica manualmente
   quando conveniente.
2. **CI remoto não verificado** — consequência direta do item 1, não um
   problema autônomo.
3. **`REPRODUCIBLE_BUILD_PROVEN=NO`** — só um build foi executado;
   reprodutibilidade bit-a-bit não foi provada (nem afirmada).
4. **Council ainda single-pass** — reafirmado (não uma novidade desta
   missão): sem limite de rodadas nem orçamento deliberativo no runtime
   atual, documentado em H4.5-D e nas release notes deste rc18.
5. `site/index.html` continua a apontar para a última release
   **realmente publicada** (`v1.3.0rc17-cockpit-conexoes`), não para
   `1.3.0rc18` — correto e deliberado enquanto rc18 não for publicado
   com assets reais; precisa ser atualizado manualmente (2 pontos
   marcados `MANUTENÇÃO` em `site/index.html`, por convenção já
   documentada em `MC43_RELEASE_PREP.md`) **depois** que a tag for
   publicada e a release do GitHub existir de fato.
