# MOTOR COUNCIL MC12-RC4 — GITHUB RELEASE PUBLICATION + WORKFLOW GUARD

## 1. Status final

STATUS_FINAL=PASS_MOTOR_COUNCIL_MC12_RC4_RELEASE_PUBLISHED

O GitHub Release existente para `v1.3.0rc4-motor-council-dry-run` foi
corrigido para usar o corpo técnico (título, postura de segurança,
validação, instalação), confirmado `prerelease=true` / `draft=false` /
não-latest. O workflow `.github/workflows/release.yml` foi endurecido com um
step que resolve `prerelease`/`make_latest` a partir do nome da tag, para
que a próxima tag `v*rc*` saia correta sem precisar de correção manual
pós-publicação. Nenhuma tag foi movida, recriada ou apagada; nenhum código
de runtime ou teste foi alterado.

## 2. Baseline

| Item | Resultado |
|---|---|
| BASELINE_HEAD | 96ddb52 |
| BASELINE_TAG | v1.3.0rc4-motor-council-dry-run-1-g96ddb52 |
| GIT_STATUS | CLEAN (antes das mudanças) |
| GIT_FSCK | PASS (1 commit dangling pré-existente, benigno) |
| RUFF | PASS |
| PYTEST | PASS_778 |
| BUILD | PASS_IN_TMP_SANDBOX_FS_QUIRK |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | WARN (LOG_LEGACY_UNANCHORED, esperado) |

## 3. Release RC4

| Item | Resultado (antes) | Resultado (depois) |
|---|---|---|
| RELEASE_EXISTS | true | true |
| RELEASE_TAG | `v1.3.0rc4-motor-council-dry-run` | inalterado |
| RELEASE_TITLE | `v1.3.0rc4-motor-council-dry-run` (genérico, só a tag) | `NOMOS v1.3.0rc4 — Motor Council Dry-run` |
| RELEASE_DRAFT | false | false |
| RELEASE_PRERELEASE | true (corrigido na MC11-RC4) | true (confirmado novamente) |
| RELEASE_LATEST | false (`/releases/latest`→404) | false (`/releases/latest`→404, reconfirmado após a correção do corpo) |
| RELEASE_BODY_IS_GENERIC | true (616 caracteres, template padrão do workflow) | false (2385 caracteres, conteúdo técnico) |
| RELEASE_URL | `https://github.com/Voltolini-SPACE/NOMOS/releases/tag/v1.3.0rc4-motor-council-dry-run` | inalterada |
| LATEST_ENDPOINT | 404 | 404 |

TAG_NAME=v1.3.0rc4-motor-council-dry-run
TAG_COMMIT=10a7cc75ab2ea2d05ca0c0a400198cc1b4d25ac0
TAG_OBJECT=78f04733bebb858811c98556802396c17a1cb432
TAG_MOVED=false
TAG_DELETED=false

## 4. Correções aplicadas

- Release body técnico aplicado (a partir de `docs/missions/
  GITHUB_RELEASE_v1.3.0rc4_MOTOR_COUNCIL_DRY_RUN.md`, adaptado para um
  release já publicado — sem a linguagem "draft only"/"tag not created",
  já que a tag existe desde a MC11-RC4): título, resumo, itens incluídos,
  postura de segurança (`REAL_ENGINE_EXECUTION=false` etc.), bloco de
  validação (`PYTEST=778`, `CI=17/17`), itens não incluídos, instruções de
  instalação e link de changelog completo. Aplicado via
  `PATCH /repos/.../releases/349077053` (título, corpo, `draft=false`,
  `prerelease=true`, `make_latest=false`) — nenhum asset novo anexado.
- `prerelease=true` confirmado (já estava correto desde a correção da
  MC11-RC4; reconfirmado nesta missão).
- `latest=false` confirmado.
- `/releases/latest=404` confirmado antes e depois desta missão.
- Workflow `release.yml` protegido para tags RC: novo step
  `Resolve release flags` decide `prerelease`/`make_latest` a partir de
  `github.ref_name` (`*rc*` ⇒ `prerelease=true`/`make_latest=false`; caso
  contrário ⇒ `prerelease=false`/`make_latest=legacy`), e o step
  `Criar release no GitHub` (`softprops/action-gh-release@v2`) agora lê
  esses outputs em vez de usar o comportamento padrão da action.

## 5. Workflow guard

Regra implementada em `.github/workflows/release.yml`, dentro do job
`publicar`, antes do step que cria o release:

```yaml
- name: Resolve release flags
  id: release_flags
  shell: bash
  run: |
    if [[ "${{ github.ref_name }}" == *rc* ]]; then
      echo "prerelease=true" >> "$GITHUB_OUTPUT"
      echo "make_latest=false" >> "$GITHUB_OUTPUT"
    else
      echo "prerelease=false" >> "$GITHUB_OUTPUT"
      echo "make_latest=legacy" >> "$GITHUB_OUTPUT"
    fi

- name: Criar release no GitHub
  uses: softprops/action-gh-release@v2
  with:
    prerelease: ${{ steps.release_flags.outputs.prerelease }}
    make_latest: ${{ steps.release_flags.outputs.make_latest }}
    # ...files/body inalterados
```

Efeito: qualquer tag futura cujo nome contenha `rc` (`v1.3.0rc5`,
`v2.0.0rc1-qualquer-sufixo`, etc.) será publicada automaticamente como
`prerelease=true`/`make_latest=false` — nunca vira "latest" nem aparece como
release final sem uma correção manual explícita e deliberada. Uma tag final
sem `rc` no nome (ex.: `v1.3.0`) preserva o comportamento anterior
(`make_latest=legacy`, que deixa o GitHub decidir pela ordem cronológica
entre releases não-prerelease).

Validação por leitura/grep (sem criar tag de teste):

```text
RELEASE_WORKFLOW_RC_PRERELEASE_GUARD=true
RELEASE_WORKFLOW_RC_LATEST_FALSE_GUARD=true
```

Confirmado: `grep -n "prerelease"`, `grep -n "make_latest\|latest"` e
`grep -n "rc"` no arquivo mostram as linhas do novo step e da referência aos
seus outputs. YAML validado com `python3 -c "import yaml; yaml.safe_load(...)"`
— sintaticamente correto.

## 6. O que NÃO foi feito

- nenhuma tag movida
- nenhuma tag recriada
- nenhuma tag apagada
- nenhum PyPI
- nenhum código runtime alterado (`src/**` intocado)
- nenhum teste alterado (`tests/**` intocado; suíte permanece 778)
- nenhum comando CLI/chat real implementado
- nenhuma execução real
- nenhum asset binário novo anexado ao release (o wheel/sdist/instaladores
  já existentes, gerados pelo workflow no momento da tag, permanecem)
- nenhuma tag de teste criada para validar o workflow (validado por
  leitura/grep/YAML lint, conforme a missão pediu)

## 7. Validação final

| Item | Resultado |
|---|---|
| RUFF | PASS |
| PYTEST | PASS_778 (inalterado) |
| BUILD | PASS_IN_TMP_SANDBOX_FS_QUIRK |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | WARN (LOG_LEGACY_UNANCHORED, esperado) |
| GIT_FSCK | PASS |
| GIT_STATUS | arquivos tocados restritos a `.github/workflows/release.yml`, `docs/missions/*`, `CHANGELOG.md` |
| `git diff --name-only HEAD -- src tests pyproject.toml setup.cfg` | vazio |
| YAML de `release.yml` | válido (`yaml.safe_load` sem erro) |
| CI_STATUS | PASS |
| CI_JOBS | 17/17 |
| Release RC4 pós-CI: título/corpo/prerelease/latest | confirmados corretos |
| `git tag --points-at HEAD` | vazio — nenhuma tag nova |

## 8. Riscos remanescentes

- O guard depende da substring `"rc"` aparecer em `github.ref_name`. Uma tag
  final hipotética que contivesse "rc" por acidente no nome (pouco provável
  dado o padrão de nomenclatura já usado neste repositório) seria tratada
  como pre-release por engano; o padrão atual de nomes (`vX.Y.Z` para final,
  `vX.Y.ZrcN[-sufixo]` para candidatos) não tem esse risco na prática.
- O corpo do release ainda não reaproveita `generate_release_notes: true`
  de forma estruturada junto com o texto técnico — a action anexa notas
  automáticas separadamente; isso é comportamento herdado do workflow
  original e não foi alterado nesta missão.
- Este ajuste só se aplica a partir de agora; os 4 releases anteriores a
  `v1.3.0rc4-motor-council-dry-run` não foram tocados nem reavaliados (fora
  do escopo desta missão).

## 9. Próximo passo recomendado

MC13-RC4 — Post-release Verification + Public README/Docs Alignment,
validando links, badges, README e documentação pública, sem implementar
runtime novo.
