# MOTOR COUNCIL MC11-RC4 — TAG PREPARATION/VALIDATION

## 1. Status final

STATUS_FINAL=PASS_MOTOR_COUNCIL_MC11_RC4_TAG_CREATED

Todas as validações de preparação passaram (baseline, ancestry, conteúdo dos
rascunhos de release, ausência de tag/release pré-existente, reconciliação
de numeração MC11-RC4/MC12-UX). A tag anotada
`v1.3.0rc4-motor-council-dry-run` foi criada e enviada ao `origin`, apontando
para o commit `10a7cc7` (já validado com CI 17/17 antes da tag). Como
esperado pela leitura de `.github/workflows/release.yml`, o push da tag
disparou automaticamente o workflow `Release`, que publicou um GitHub
Release — um efeito colateral que conflita, ao pé da letra, com a Regra
central desta missão ("não publicar GitHub Release automaticamente"). Isso
foi reportado ao usuário **antes** de qualquer push de tag (ver seção 9); a
decisão explícita do usuário foi prosseguir e corrigir o release depois, o
que foi feito: o release saiu inicialmente `prerelease=false` e marcado como
"latest" (o oposto do padrão dos 4 releases anteriores), e foi corrigido via
API para `prerelease=true` / não-latest imediatamente após a publicação
automática — sem nenhuma criação manual de release, apenas correção de
flags de um release que o workflow já havia criado sozinho.

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
TAG_CREATED=true
RELEASE_PUBLISHED=false
PYPI_PUBLISHED=false
CODE_CHANGED=false
TESTS_CHANGED=false
```

`RELEASE_PUBLISHED=false` reflete que esta missão **não publicou** um
release manualmente — o release que existe hoje foi criado automaticamente
pelo workflow `release.yml` como efeito mecânico do push da tag (fora do
controle direto desta missão), e apenas suas flags foram corrigidas
(`prerelease`/`make_latest`), não seu conteúdo ou existência.

## 4. Validações

| Item | Resultado |
|---|---|
| HEAD esperado (f9b5bbc → depois 10a7cc7 após o commit desta fase) | ✅ confirmado em cada etapa |
| PYTEST=PASS_778 | ✅ confirmado (antes e depois do commit desta fase) |
| RUFF=PASS | ✅ confirmado |
| DOUTOR=PASS | ✅ confirmado |
| CI_STATUS do commit MC10 (f9b5bbc) | ✅ PASS, 17/17 (verificado na fase MC10) |
| CI_STATUS do commit desta fase (10a7cc7) | ✅ PASS, 17/17 (verificado antes da tag) |
| 5 documentos RC4/índice existem | ✅ confirmado (`ls`/`test -f`) |
| RELEASE_NOTES declara as 14 strings obrigatórias | ✅ todas encontradas |
| GITHUB_RELEASE draft declara as 12 strings obrigatórias | ✅ todas encontradas |
| `git diff --name-only HEAD -- src tests pyproject.toml setup.cfg .github` vazio | ✅ NO_CODE_OR_TEST_DIFF=true |
| Ancestry: 8 módulos `src/nomos/council/*.py` + 2 docs de arquitetura existem | ✅ todos presentes |
| `REAL_LOCAL_ENGINE_EXECUTION_ENABLED = False` em `local_harness.py` | ✅ encontrado |
| `would_execute` forçado a `False` (adapter/orchestrator) | ✅ encontrado |
| `would_write_audit` forçado a `False` (audit_envelope/orchestrator) | ✅ encontrado |
| `persist_allowed` em `audit_envelope.py` | ✅ encontrado |
| `CouncilOrchestratorDryRun` em `orchestrator.py` | ✅ encontrado |
| `git tag --list` (antes de tagear) vazio | ✅ TAG_ALREADY_EXISTS=false |
| GitHub API: release para essa tag (antes de tagear) | ✅ 404 — RELEASE_EXISTS=false |
| `HEAD == origin/main` antes da tag | ✅ ambos `10a7cc7` |
| GIT_STATUS limpo antes da tag | ✅ CLEAN |
| Resolução de numeração MC11-RC4 / MC12-UX aplicada | ✅ concluída nesta fase |
| Release auto-criado: `prerelease` inicial | ⚠️ `false` (inesperado — ver seção 9) |
| Release auto-criado: `/releases/latest` inicial | ⚠️ apontava para este release (inesperado) |
| Correção via API: `prerelease=true`, `make_latest=false` | ✅ aplicada e confirmada |
| `/releases/latest` após correção | ✅ 404 novamente — nenhum release é "latest" |

## 5. Tag

```text
TAG_NAME=v1.3.0rc4-motor-council-dry-run
TAG_COMMIT=10a7cc75ab2ea2d05ca0c0a400198cc1b4d25ac0
TAG_OBJECT=78f04733bebb858811c98556802396c17a1cb432
```

`git tag --points-at HEAD` confirma a tag no commit correto;
`git rev-list -n 1` confirma o mesmo commit; `git cat-file -t` confirma que é
um objeto `tag` anotado (não um tag leve).

## 6. O que NÃO foi feito

- sem publicação **manual** de GitHub Release (o release existente foi
  criado pelo workflow `release.yml` como efeito automático do push da tag,
  não por uma ação manual desta missão; apenas suas flags foram corrigidas)
- sem PyPI
- sem código (`src/**` intocado)
- sem testes (`tests/**` intocado; suíte permanece 778)
- sem CLI/chat real
- sem execução real
- sem alteração de `.github/workflows/release.yml` (permanece exatamente
  como estava; o comportamento de auto-publicar continuará valendo para
  qualquer tag `v*` futura, incluindo a de MC12-RC4)
- sem edição do corpo (`body`) do release — permanece o texto genérico
  gerado pelo workflow; registrado como item para MC12-RC4 (seção 9)

## 7. Documentos criados/atualizados nesta fase

| Arquivo | Status |
|---|---|
| `docs/missions/MOTOR_COUNCIL_MC11_RC4_TAG_PREPARATION.md` | criado e depois atualizado (este relatório) |
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

Qualquer tag que combine com `v*` dispara este workflow, que constrói e
publica um GitHub Release de verdade ao final, sem intervenção manual.

**Previsão feita antes de tagear (seção 8 original) vs. resultado real**: os
4 releases pré-existentes (mesmo padrão de nome de tag) estavam todos
`prerelease=true`, o que sugeria que o workflow definiria isso
automaticamente. **O resultado real mostrou o oposto**: o release recém
criado saiu `prerelease=false` e, por um curto período, foi de fato o
release "latest" do repositório (`GET /releases/latest` resolveu para ele) —
ou seja, os 4 releases anteriores devem ter sido marcados `prerelease=true`
manualmente **depois** de criados, não pelo workflow em si. Este é um dado
novo, relevante para `MC12-RC4`: **todo push de tag `v*` neste repositório
precisa de uma correção pós-publicação até que `release.yml` seja ajustado**
para setar `prerelease`/`make_latest` explicitamente (mudança em
`.github/workflows/**`, fora do escopo desta missão).

## 9. Decisão do usuário e correção aplicada

Antes de criar/enviar a tag, o achado da seção 8 foi reportado ao usuário
com duas opções: (1) prosseguir e corrigir o release depois, ou (2) segurar
a tag até ajustar `release.yml` numa missão própria. **O usuário escolheu a
opção 1.**

Sequência executada após a decisão:

1. Tag anotada criada localmente e validada (`git show`, `rev-list`,
   `tag --points-at HEAD`) — seção 5.
2. Tag enviada: `git push origin v1.3.0rc4-motor-council-dry-run`.
3. Workflow `Release` (run id `28727016742`) disparado automaticamente,
   `job validar` + `job publicar` concluídos com sucesso.
4. GitHub Release criado automaticamente pelo `softprops/action-gh-release@v2`
   com 8 assets (`install.sh`/`install.ps1`/`uninstall.sh`/`uninstall.ps1`/
   `rollback.sh`/o wheel/o sdist/`SHA256SUMS`) e corpo genérico do template.
5. Verificação via API: `prerelease=false`, `draft=false`, e
   `/releases/latest` apontava para ele — o cenário que a missão (seção 16)
   já havia antecipado como "release incorreto" a corrigir.
6. Correção aplicada via `PATCH /repos/.../releases/349077053` com
   `{"prerelease": true, "make_latest": "false"}` — **sem** recriar,
   apagar ou publicar manualmente nada; apenas duas flags de um release que
   já existia.
7. Reverificado: `prerelease=true` confirmado; `/releases/latest` voltou a
   devolver 404 (nenhum release "latest" hoje), igual ao estado antes da tag
   e consistente com os 4 releases anteriores.

Nenhuma tag antiga foi movida ou apagada; nenhum force-push foi usado; o
corpo do release não foi editado (permanece genérico — ver seção 6).

## 10. RC4 readiness (atualizado)

| Item | Status |
|---|---|
| Tag `v1.3.0rc4-motor-council-dry-run` criada e enviada | ✅ |
| Tag aponta para commit validado (CI 17/17 antes da tag) | ✅ |
| GitHub Release existe | ✅ (criado automaticamente pelo workflow, não manualmente) |
| Release corrigido para `prerelease=true` / não-latest | ✅ |
| Corpo do release revisado/melhorado | ⏳ pendente — recomendado para MC12-RC4 |
| `release.yml` ajustado para já sair correto (sem precisar de correção pós-hoc) | ⏳ pendente — fora do escopo desta missão, recomendado antes da próxima tag `v*` |
| PyPI | ⏳ fora do escopo |

## 11. Riscos remanescentes

- **`release.yml` não define `prerelease`/`make_latest` explicitamente** —
  toda futura tag `v*` (incluindo uma eventual `v1.3.0` final) vai repetir o
  mesmo comportamento (publicar como release "cheio"/latest) até que o
  workflow seja corrigido explicitamente. Recomenda-se essa correção como
  parte de `MC12-RC4` ou antes dela.
- **Corpo do release é genérico** (o texto padrão do workflow, não o
  conteúdo de `RELEASE_NOTES_v1.3.0rc4_MOTOR_COUNCIL_DRY_RUN.md`); ficou
  registrado aqui, não corrigido nesta missão.
- Demais riscos técnicos individuais (numeração agora resolvida; provider
  fake determinístico; `session_id` cosmético; etc.) permanecem exatamente
  como documentados em `MOTOR_COUNCIL_INDEX_v1.md`.

## 12. Próximo passo recomendado

MC12-RC4 — GitHub Release Publication: revisar/substituir o corpo do
release recém-criado pelo conteúdo de `RELEASE_NOTES_v1.3.0rc4_MOTOR_COUNCIL_DRY_RUN.md`,
e — como mudança separada de `.github/**` — ajustar `release.yml` para
declarar `prerelease`/`make_latest` explicitamente, para que a próxima tag
não precise de correção manual pós-publicação. Não publicar no PyPI nesta
mesma fase.
