# MOTOR COUNCIL MC17-UX — CHAT DRY-RUN COMMAND SPEC/IMPLEMENTATION PLAN

## 1. Status final

STATUS_FINAL=PASS_MOTOR_COUNCIL_MC17_UX_CHAT_DRY_RUN_SPEC_PLAN

Especificação canônica do futuro `/conselho simular` (chat dry-run) criada em
`docs/architecture/MOTOR_COUNCIL_CHAT_DRY_RUN_SPEC_v1.md` (20 seções), mais um
ponteiro na UX spec. Nada foi implementado: `/conselho` continua
desabilitado/fail-closed, nenhum código ou teste foi tocado, e a suíte segue
em 851. Nenhuma tag/release/PyPI.

## 2. Baseline

| Item | Resultado |
|---|---|
| BASELINE_HEAD | 2d89459 |
| BASELINE_TAG | v1.3.0rc4-motor-council-dry-run-10-g2d89459 |
| GIT_STATUS | CLEAN (antes das mudanças) |
| GIT_FSCK | PASS (1 commit dangling pré-existente, benigno) |
| RUFF | PASS |
| PYTEST | PASS_851 |
| BUILD | PASS_IN_TMP_SANDBOX_FS_QUIRK |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | WARN (LOG_LEGACY_UNANCHORED, esperado) |

## 3. Escopo

```text
SPEC_ONLY=true
CHAT_DRY_RUN_IMPLEMENTED=false
CHAT_ENABLED=false
REAL_ENGINE_EXECUTION=false
REAL_POLICY=false
REAL_AUDIT=false
REAL_VAULT=false
PERSISTENCE=false
```

## 4. Documentos criados/atualizados

| Arquivo | Status |
|---|---|
| `docs/architecture/MOTOR_COUNCIL_CHAT_DRY_RUN_SPEC_v1.md` | criado (20 seções) |
| `docs/architecture/MOTOR_COUNCIL_UX_SPEC_v1.md` | atualizado — 1 nota de progresso apontando para a nova spec; nenhum outro conteúdo alterado |
| `docs/missions/MOTOR_COUNCIL_MC17_UX_CHAT_DRY_RUN_SPEC_PLAN.md` | criado (este relatório) |
| `CHANGELOG.md` | atualizado — entrada `[Unreleased]` (Documentation / Not changed) |

## 5. O que foi especificado

- **Estado atual** explícito: no chat, `/conselho` e todos os subcomandos
  (`simular`/`perguntar`/`revisar`/`status`/`modos`) estão desabilitados/
  fail-closed; `MOTOR_COUNCIL_CHAT_ENABLED = False`; o handler devolve `None`
  para mensagens não relacionadas. A CLI já tem o dry-run funcional (MC15).
- **Futuro comando** `/conselho simular <texto>` chamando **apenas** o
  `CouncilOrchestratorDryRun`, sem harness/policy/audit/vault reais, sem
  persistência, sem eco de prompt.
- **Contratos de entrada/saída**: parsing manual de flags (padrão CLI MC15),
  `session_id` fixo `chat-conselho-simular`, saídas humana permitida
  (`[NOMOS-MC-CHAT-DRY-RUN]`), bloqueada pelo gate
  (`[NOMOS-MC-CHAT-GATE-BLOCKED]`) e negada
  (`[NOMOS-MC-CHAT-DENIED]`).
- **Privacidade e redaction**: 10 chaves proibidas de aparecer
  (prompt/content/…/bearer) e a lista de escalares seguros permitidos.
- **Flags proibidas** (10: `--real`/…/`--engine-real`) que sempre falham
  fechado, sem ecoar o token.
- **Modos** pt→interno (rapido/balanceado/critico/paranoico), `paranoico`
  implicando privado, modo inválido fail-closed.
- **Failure modes** (8 códigos `CHAT_*`).
- **Integração com `amigavel.py`** preservando o contrato `None` para
  mensagens não-`/conselho` e o fail-closed dos demais subcomandos; só
  `simular` roteia para o dry-run.
- **JSON futuro** montado à mão (escalares), com proibição explícita de
  `result.to_dict()` (que pode carregar trace/envelope), reforçando a lição
  do CLI MC15.
- **UX iniciante/avançado**: mesma informação escalar, formatação diferente,
  nunca expondo conteúdo.
- **Plano de fases** (MC18-UX handler → MC19-UX testes → MC20-UX docs, ou uma
  MC18-UX compacta) e **plano de testes futuros** (12 nomes + AST).

## 6. O que NÃO foi implementado

Confirmado:
- sem `/conselho simular` funcional
- sem orquestrador chamado
- sem motor
- sem cloud
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
| PYTEST | PASS_851 (inalterado) |
| BUILD | PASS_IN_TMP_SANDBOX_FS_QUIRK |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | WARN (LOG_LEGACY_UNANCHORED, esperado) |
| GIT_FSCK | PASS |
| `git diff --name-only HEAD -- src tests .github pyproject.toml setup.cfg` | vazio (NO_CODE_TEST_WORKFLOW_DIFF=true) |
| `/conselho` ainda desabilitado | confirmado (nenhum código de chat tocado) |
| CI_STATUS | PASS |
| CI_JOBS | 17/17 |
| `git tag --points-at HEAD` | vazio (NO_NEW_TAG_ON_HEAD=true) |

## 8. Riscos remanescentes

- Esta spec é normativa, mas não vinculante por código — a implementação
  MC18-UX deve revisá-la antes de qualquer código, pela disciplina
  `implementation-loop-100`.
- A lição-chave (nunca `result.to_dict()` no JSON; montar escalares à mão) é
  fácil de esquecer sob pressão — está registrada em §13/§16 da spec e no
  plano de testes (`test_chat_conselho_simular_does_not_use_result_to_dict`).
- Ao habilitar `simular` no chat, o ramo atual de `amigavel.py`
  (`/conselho` → tudo desabilitado) precisa ser dividido com cuidado para não
  quebrar o contrato `None` das mensagens não-`/conselho` nem o fail-closed
  dos outros subcomandos.

## 9. Próximo passo recomendado

MC18-UX — Chat Dry-run Implementation: habilitar `/conselho simular` com o
mesmo padrão seguro do CLI MC15 (novo `chat_dry_run.py` reusando
`CouncilOrchestratorDryRun`, roteamento em `amigavel.py`, prompt nunca ecoado,
JSON/escalares à mão), mantendo os demais subcomandos de `/conselho`
desabilitados.
