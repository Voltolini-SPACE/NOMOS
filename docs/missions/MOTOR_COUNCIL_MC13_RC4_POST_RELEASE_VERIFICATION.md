# MOTOR COUNCIL MC13-RC4 — POST-RELEASE VERIFICATION + PUBLIC README/DOCS ALIGNMENT

## 1. Status final

STATUS_FINAL=PASS_MOTOR_COUNCIL_MC13_RC4_POST_RELEASE_VERIFICATION

O release `v1.3.0rc4-motor-council-dry-run` foi verificado publicamente como
pre-release/não-latest, com corpo técnico; a tag foi confirmada intacta
(mesmo commit/objeto da MC11-RC4); e a documentação pública (README, índice)
foi alinhada para deixar explícito que o Motor Council está em dry-run — sem
execução real, sem CLI/chat, sem nuvem/rede/subprocess. Nenhum código,
teste, workflow, tag, release ou PyPI foi criado ou alterado.

## 2. Baseline

| Item | Resultado |
|---|---|
| BASELINE_HEAD | f48f4b7 |
| BASELINE_TAG | v1.3.0rc4-motor-council-dry-run-3-gf48f4b7 |
| GIT_STATUS | CLEAN (antes das mudanças) |
| GIT_FSCK | PASS (1 commit dangling pré-existente, benigno) |
| RUFF | PASS |
| PYTEST | PASS_778 |
| BUILD | PASS_IN_TMP_SANDBOX_FS_QUIRK |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | WARN (LOG_LEGACY_UNANCHORED, esperado) |

## 3. Release verification

| Item | Resultado |
|---|---|
| RELEASE_TAG | `v1.3.0rc4-motor-council-dry-run` |
| RELEASE_TITLE | `NOMOS v1.3.0rc4 — Motor Council Dry-run` |
| RELEASE_DRAFT | false |
| RELEASE_PRERELEASE | true |
| RELEASE_LATEST | false |
| LATEST_ENDPOINT | 404 (`GET /releases/latest` — nenhum release é "latest") |
| RELEASE_BODY_TECHNICAL | true (contém `PYTEST=778`, postura de segurança, itens incluídos/não incluídos) |
| RELEASE_URL | `https://github.com/Voltolini-SPACE/NOMOS/releases/tag/v1.3.0rc4-motor-council-dry-run` |

Verificado via GitHub REST API com `curl` autenticado (o mesmo método seguro
usado na MC12; `gh` CLI local não está autenticado com escopo suficiente —
`GH_AUTH=SKIPPED_INSUFFICIENT_SCOPE`, mas isso não afeta a verificação por
API, que é read-only).

## 4. Tag verification

| Item | Resultado |
|---|---|
| TAG_NAME | `v1.3.0rc4-motor-council-dry-run` |
| TAG_COMMIT | `10a7cc75ab2ea2d05ca0c0a400198cc1b4d25ac0` |
| TAG_OBJECT | `78f04733bebb858811c98556802396c17a1cb432` |
| TAG_TYPE | tag anotada (`git cat-file -t` ⇒ `tag`) |
| TAG_MOVED | false (mesmo commit/objeto da MC11-RC4) |
| TAG_DELETED | false |

## 5. Public docs alignment

| Arquivo | Status |
|---|---|
| `README.md` | atualizado — nova seção `## Motor Council` (em português, técnica, sem marketing) declarando dry-run/pre-release e o que está desligado; contagem de testes corrigida de 494 (obsoleta) para 778; nota de maturidade agora marca RC4 como pre-release |
| `docs/architecture/MOTOR_COUNCIL_INDEX_v1.md` | atualizado — bloco "Estado pós-release" com `RC4_RELEASE_PUBLISHED=true`, `RC4_PRERELEASE=true`, `RC4_LATEST=false`, `RELEASE_WORKFLOW_RC_GUARD=true`, `README_PUBLIC_ALIGNMENT=done`; as flags MC10 originais (`TAG_CREATED=false`/`RELEASE_PUBLISHED=false`) foram anotadas como foto histórica, não apagadas |
| `docs/missions/MOTOR_COUNCIL_MC13_RC4_POST_RELEASE_VERIFICATION.md` | criado (este relatório) |
| `CHANGELOG.md` | atualizado — seção `Documentation (MC13-RC4)` + `Not changed (MC13-RC4)` na entrada `[Unreleased]` |
| `docs/README.md` / `docs/architecture/README.md` | não existem — não foram criados (a missão marcava como opcional "se existirem") |

Conteúdo declarado publicamente no README (todos verificados por teste no
código, não por convenção):

```text
Real engine execution: disabled (REAL_LOCAL_ENGINE_EXECUTION_ENABLED = False)
CLI/chat commands: not implemented (spec-only)
Cloud/network/subprocess: not used
Policy gate: dry-run only (A0–A6 simulado)
Audit envelope: dry-run, metadata-only (would_write_audit=false)
Private mode: persist_allowed=false ponta a ponta
RC4: pre-release, não "latest"
```

## 6. O que NÃO foi feito

- nenhuma tag criada/movida/apagada
- nenhum release criado (o release RC4 já existia da MC11/MC12; aqui só foi
  **verificado**, não alterado)
- nenhum PyPI
- nenhum código runtime alterado (`src/**` intocado)
- nenhum teste alterado (`tests/**` intocado; suíte permanece 778)
- nenhum CLI/chat real implementado
- nenhuma execução real
- nenhum workflow alterado (`.github/**` intocado nesta fase)

## 7. Validação final

| Item | Resultado |
|---|---|
| RUFF | PASS |
| PYTEST | PASS_778 (inalterado) |
| BUILD | PASS_IN_TMP_SANDBOX_FS_QUIRK |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | WARN (LOG_LEGACY_UNANCHORED, esperado) |
| GIT_FSCK | PASS |
| GIT_STATUS | arquivos tocados restritos a `README.md`, `docs/architecture/MOTOR_COUNCIL_INDEX_v1.md`, `docs/missions/MOTOR_COUNCIL_MC13_RC4_POST_RELEASE_VERIFICATION.md`, `CHANGELOG.md` |
| `git diff --name-only -- src tests pyproject.toml setup.cfg .github` | vazio (NO_CODE_TEST_WORKFLOW_DIFF=true) |
| CI_STATUS | PASS |
| CI_JOBS | 17/17 |
| `git tag --points-at HEAD` | vazio (NO_NEW_TAG_ON_HEAD=true) |

## 8. Riscos remanescentes

- O README ainda descreve o restante do NOMOS (comandos `nomos …`,
  instalação) como já usável; a nova seção deixa claro que **o Motor Council
  especificamente** está em dry-run, mas um leitor apressado poderia
  generalizar. Mitigação: a seção é explícita e a nota de maturidade repete
  o ponto.
- A contagem de testes agora aparece em dois lugares (README e vários
  relatórios); se a suíte crescer numa fase futura, o README precisará ser
  atualizado de novo — não há verificação automática de que o número no
  README bate com a suíte.
- O corpo do release publicado no GitHub e o `README.md` são mantidos em
  sincronia manualmente; uma edição futura em um não atualiza o outro
  automaticamente.

## 9. Próximo passo recomendado

MC14-UX — CLI Skeleton Disabled, registrando a UX futura como comando
desabilitado/fail-closed (o comando aparece no `--help` mas recusa executar),
ainda sem chamar o orquestrador por padrão e sem execução real de motor.
