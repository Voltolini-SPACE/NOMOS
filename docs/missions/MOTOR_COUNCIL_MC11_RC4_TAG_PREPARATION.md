# MOTOR COUNCIL MC11-RC4 — TAG PREPARATION/VALIDATION

## 1. Status final

STATUS_FINAL=WARN_MOTOR_COUNCIL_MC11_RC4_TAG_NOT_CREATED

Todas as validações de preparação passaram (baseline, ancestry, conteúdo dos
rascunhos de release, ausência de tag/release pré-existente, reconciliação
de numeração MC11-RC4/MC12-UX). A criação e o push da tag
`v1.3.0rc4-motor-council-dry-run` foram **conscientemente pausados** antes de
executar, porque a validação encontrou um efeito colateral automático não
coberto explicitamente pela missão: o workflow `.github/workflows/release.yml`
dispara em **qualquer** push de tag `v*` e publica um GitHub Release
automaticamente ao final. Isso é reportado como um bloqueio honesto para
decisão do usuário antes de prosseguir — ver seção 9.

## 2. Baseline

| Item | Resultado |
|---|---|
| BASELINE_HEAD | f9b5bbc |
| BASELINE_TAG | v1.2.0rc3-audit-anchored-34-gf9b5bbc |
| GIT_STATUS | CLEAN (antes das mudanças) |
| GIT_FSCK | PASS (1 commit dangling pré-existente, benigno) |
| RUFF | PASS |
| PYTEST | PASS_778 |
| BUILD | PASS_IN_TMP_SANDBOX_FS_QUIRK |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | WARN (LOG_LEGACY_UNANCHORED, esperado) |

## 3. Escopo

```text
RC4_TAG_PREPARATION=true
TAG_CREATED=false
RELEASE_PUBLISHED=false
PYPI_PUBLISHED=false
CODE_CHANGED=false
TESTS_CHANGED=false
```

## 4. Validações

| Item | Resultado |
|---|---|
| HEAD esperado (f9b5bbc) | ✅ confirmado |
| PYTEST=PASS_778 | ✅ confirmado |
| RUFF=PASS | ✅ confirmado |
| DOUTOR=PASS | ✅ confirmado |
| CI_STATUS do commit MC10 (f9b5bbc) | ✅ PASS, 17/17 (verificado na fase MC10) |
| 5 documentos RC4/índice existem | ✅ confirmado (`ls`/`test -f`) |
| RELEASE_NOTES declara as 14 strings obrigatórias (PREPARED_ONLY, TAG_CREATED=false, RELEASE_PUBLISHED=false, e as 11 garantias) | ✅ todas encontradas |
| GITHUB_RELEASE draft declara as 12 strings obrigatórias | ✅ todas encontradas |
| `git diff --name-only HEAD -- src tests pyproject.toml setup.cfg .github` vazio | ✅ NO_CODE_OR_TEST_DIFF=true |
| Ancestry: 8 módulos `src/nomos/council/*.py` + 2 docs de arquitetura existem | ✅ todos presentes |
| `REAL_LOCAL_ENGINE_EXECUTION_ENABLED = False` em `local_harness.py` | ✅ encontrado |
| `would_execute` forçado a `False` (adapter/orchestrator) | ✅ encontrado |
| `would_write_audit` forçado a `False` (audit_envelope/orchestrator) | ✅ encontrado |
| `persist_allowed` em `audit_envelope.py` | ✅ encontrado (regra de modo privado) |
| `CouncilOrchestratorDryRun` em `orchestrator.py` | ✅ encontrado |
| `git tag --list "v1.3.0rc4-motor-council-dry-run"` vazio | ✅ TAG_ALREADY_EXISTS=false |
| GitHub API: release para essa tag | ✅ 404 — RELEASE_EXISTS=false |
| GitHub API: `/releases/latest` | 404 — nenhum release é "latest" hoje (todos os 4 releases existentes são `prerelease=true`) |
| Resolução de numeração MC11-RC4 / MC12-UX aplicada em `MOTOR_COUNCIL_UX_SPEC_v1.md` e `MOTOR_COUNCIL_INDEX_v1.md` | ✅ concluída nesta fase |

## 5. Tag

```text
TAG_NAME=v1.3.0rc4-motor-council-dry-run
TAG_COMMIT=(pendente — ver seção 9; será o commit desta própria fase, após push e CI verde)
TAG_OBJECT=(pendente — tag ainda não criada)
```

## 6. O que NÃO foi feito

- sem GitHub Release (nem manual, nem confirmado como automático ainda —
  ver seção 9)
- sem PyPI
- sem código (`src/**` intocado)
- sem testes (`tests/**` intocado; suíte permanece 778)
- sem CLI/chat real
- sem execução real
- **sem a tag `v1.3.0rc4-motor-council-dry-run` ainda** (pausado
  conscientemente — ver seção 9)

## 7. Documentos criados/atualizados nesta fase

| Arquivo | Status |
|---|---|
| `docs/missions/MOTOR_COUNCIL_MC11_RC4_TAG_PREPARATION.md` | criado (este relatório) |
| `docs/architecture/MOTOR_COUNCIL_UX_SPEC_v1.md` | atualizado — seção 20 renumerada (MC11–MC16 → MC11-RC4/MC12-UX–MC17-UX) e todas as referências cruzadas ajustadas; nenhum outro conteúdo alterado |
| `docs/architecture/MOTOR_COUNCIL_INDEX_v1.md` | atualizado — seções 12, 17, 18, 19 refletem a numeração reconciliada e marcam o risco como resolvido |
| `CHANGELOG.md` | atualizado — entrada `[Unreleased]` ampliada com a preparação de MC11-RC4 |

## 8. Achado — gatilho automático de Release no push de tag

Leitura de `.github/workflows/release.yml` (somente leitura; nenhuma
alteração feita, conforme escopo proibido desta missão):

```yaml
on:
  push:
    tags: ["v*"]
# ...
jobs:
  publicar:
    needs: validar
    steps:
      # build wheel+sdist, smoke test
      - name: Criar release no GitHub
        uses: softprops/action-gh-release@v2
        with:
          files: dist/*
          generate_release_notes: true
          body: |
            Consulte o CHANGELOG.md ...
```

Qualquer tag que combine com `v*` — incluindo
`v1.3.0rc4-motor-council-dry-run` — dispara este workflow, que **constrói e
publica um GitHub Release de verdade** ao final, sem intervenção manual.
Evidência empírica (via API do GitHub, `GET /repos/.../releases`): os 4
releases já publicados por este mesmo workflow, todos com nomes de tag no
mesmo padrão (`vX.Y.ZrcN-sufixo`), saíram **todos** com `prerelease=true` —
o que sugere fortemente (mas não garante com 100% de certeza sem uma leitura
completa do código-fonte da action `softprops/action-gh-release@v2`) que a
nova tag também sairia `prerelease=true` e não passaria a ser "latest"
(`GET /releases/latest` hoje devolve 404 — não há nenhum release "latest"
atualmente, consistente com os 4 existentes serem todos prerelease).

Isso não muda o fato central: a **Regra central** desta missão diz "Não
publicar GitHub Release automaticamente" e o **Escopo proibido** lista
"GitHub Release" como algo a não fazer — e o roteiro desta trilha (seção 19
do índice) reserva a publicação do release para uma fase futura e separada
(`MC12-RC4`). Publicar a tag agora publicaria também um Release de verdade
como efeito colateral mecânico, ainda que provavelmente bem-formado
(`prerelease=true`), antes da fase `MC12-RC4` explicitamente planejada para
isso.

## 9. Bloqueio reportado — decisão do usuário necessária

**Não criei nem enviei a tag `v1.3.0rc4-motor-council-dry-run` ao `origin`
nesta execução.** Todas as validações anteriores à criação da tag (seções 2
e 4 acima) passaram; o único passo pendente é a criação/push da tag em si
(seção 14 da missão), que dispararia automaticamente `release.yml` e
publicaria um GitHub Release — algo que a Regra central desta mesma missão
proíbe fazer "automaticamente".

Duas opções foram levadas ao usuário fora deste documento (na resposta de
chat), e a que for escolhida deve ser registrada aqui numa atualização
futura deste relatório:

1. Prosseguir agora: criar e enviar a tag, aceitar que `release.yml` vai
   publicar um Release automaticamente, e imediatamente validar/corrigir
   suas flags (`prerelease=true`, não-latest) — o que a própria missão já
   antecipa como aceitável na seção 16 ("verificar e corrigir apenas se
   necessário").
2. Aguardar: não criar a tag nesta sessão; tratar o ajuste do workflow
   (ex.: um `if` que pule o job `publicar` para tags com sufixo
   `-motor-council-dry-run`, ou que force `prerelease: true` /
   `make_latest: false` explicitamente) como uma mudança de `.github/**`
   fora do escopo desta missão, a ser feita numa mission própria antes de
   qualquer tag `v*` ser enviada.

## 10. Próximo passo recomendado

Aguardar a decisão do usuário (seção 9). Se a opção 1 for escolhida: criar e
enviar a tag imediatamente após esta decisão, validar o Release
auto-publicado, e atualizar este relatório para
`STATUS_FINAL=PASS_MOTOR_COUNCIL_MC11_RC4_TAG_CREATED`. Se a opção 2 for
escolhida: abrir uma mission separada para ajustar `release.yml` antes de
qualquer nova tentativa de tag `v*`.
