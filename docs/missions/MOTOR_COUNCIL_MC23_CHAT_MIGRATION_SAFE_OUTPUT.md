# MOTOR COUNCIL MC23 — CHAT MIGRATION TO SHARED SAFE OUTPUT HELPER

## 1. Status final

STATUS_FINAL=PASS_MOTOR_COUNCIL_MC23_CHAT_MIGRATION_SAFE_OUTPUT

O comando `/conselho simular` do chat foi migrado para consumir o helper
compartilhado `src/nomos/council/safe_output.py`, espelhando a migração do CLI
(MC22): a **estrutura segura** e o **JSON** de saída agora vêm de
`build_safe_output` + `render_json_output` (o chat não monta mais o JSON à mão,
não importa `json`, e não lê o resultado do orquestrador além de
`allowed`/`blocked`/`failure_code`, isolado no helper). A resposta **humana** do
chat ficou mais simples e amigável, sem jargão e sem vazar nada. O CLI **não**
foi alterado (`cli_dry_run.py`/`cli.py` intocados) e o **helper** não foi
alterado (`safe_output.py` intocado). 15 testes novos; suíte 937 → 952. Nenhuma
tag/release/PyPI; nenhum `.github/`, `pyproject.toml` ou `setup.cfg` alterado.

## 2. Baseline

| Item | Resultado |
|---|---|
| BASELINE_HEAD | f9f18be |
| BASELINE_TAG | v1.3.0rc4-motor-council-dry-run-23-gf9f18be |
| GIT_STATUS | CLEAN (antes das mudanças) |
| GIT_FSCK | PASS (1 commit dangling pré-existente, benigno) |
| RUFF | PASS |
| PYTEST | PASS_937 (antes) → PASS_952 (depois) |
| BUILD | PASS_IN_TMP_SANDBOX_FS_QUIRK |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | WARN (LOG_LEGACY_UNANCHORED, esperado) |
| COBERTURA (chat_dry_run.py) | 92% |

## 3. Escopo

```text
CHAT_MIGRATED_TO_SAFE_OUTPUT=true
CLI_MIGRATED_IN_MC23=false
RUNTIME_REAL_EXECUTION=false
REAL_ENGINE_EXECUTION=false
REAL_POLICY=false
REAL_AUDIT=false
REAL_VAULT=false
PERSISTENCE=false
```

## 4. O que foi alterado

| Arquivo | Mudança |
|---|---|
| `src/nomos/council/chat_dry_run.py` | migrado ao helper: importa `build_safe_output`/`render_json_output`; removeu o `_render_json` manual e o `import json`; o JSON agora sai de `render_json_output(build_safe_output(..., interface="chat", ...))` (10 campos); mensagens humanas trocadas por versões amigáveis; `_render_human` lê só o `CouncilSafeOutput` |
| `tests/council/test_chat_conselho_dry_run.py` | +15 testes (migração + UX + regressão); os 35 testes anteriores continuam verdes |
| `tests/council/test_cli_conselho_dry_run.py` | **1 teste ajustado**: o `test_chat_dry_run_untouched` (escrito na MC22) afirmava que o chat **não** usava o helper; como a MC23 migra o chat, foi renomeado para `test_chat_dry_run_migrated_to_helper_in_mc23` e a asserção invertida. É ajuste de **teste**, não do código do CLI |
| `docs/missions/MOTOR_COUNCIL_MC23_CHAT_MIGRATION_SAFE_OUTPUT.md` | este relatório |
| `docs/architecture/MOTOR_COUNCIL_INDEX_v1.md` | ponte: `SHARED_HELPER_ADOPTED_BY_CHAT=true` |
| `docs/architecture/MOTOR_COUNCIL_CHAT_DRY_RUN_SPEC_v1.md` | ponte: nota de que a saída foi migrada ao helper (MC23) |
| `CHANGELOG.md` | entrada `[Unreleased]` (Changed/Security/Not changed) |

**Não alterados** (confirmado por `git diff` vazio): `cli_dry_run.py`, `cli.py`
(código do CLI intocado), `safe_output.py` (helper intocado), `amigavel.py`,
`orchestrator.py`, `local_harness.py`, `policy_gate.py`, `audit_envelope.py`,
`.github/`, `pyproject.toml`, `setup.cfg`.

## 5. UX simples (para pessoas sem experiência técnica)

A resposta humana do chat foi reescrita para ser clara e sem jargão:

**Sucesso:**

```text
[NOMOS-MC-CHAT-DRY-RUN] Simulação segura concluída.

Nada foi executado de verdade.
Nada foi salvo.
Nenhum dado sensível foi exibido.

Status:
DRY_RUN=true
REAL_ENGINE_EXECUTION=false
REAL_POLICY=false
REAL_AUDIT=false
REAL_VAULT=false
PERSISTENCE=false
```

**Bloqueado pelo gate:**

```text
[NOMOS-MC-CHAT-GATE-BLOCKED] A simulação foi bloqueada por segurança.

Nada foi executado.
Nada foi salvo.
O conteúdo bloqueado não será exibido.
```

**Opção não permitida / uso incorreto (sem ecoar a flag nem o texto):**

```text
[NOMOS-MC-CHAT-DENIED] Este comando não pode ser usado com essa opção.

Nada foi executado.
Nada foi salvo.
```

Um teste garante que a resposta humana **não** contém jargão (`orchestrator`,
`envelope`, `payload`, `failure_code`, `to_dict`, etc.). Os detalhes técnicos
completos continuam disponíveis no `--json`.

**Decisão de produto (mesma da MC22):** a segurança e o **JSON** são unificados
no helper (fonte única), mas o **texto humano** é específico do chat e
amigável. As mensagens humanas leem **apenas** os campos escalares seguros do
`CouncilSafeOutput`, então continuam sem vazamento.

## 6. Contrato de JSON (10 campos)

O `--json` do chat passou a emitir os **10 campos** do helper (igual ao CLI na
MC22): acrescentou `interface` (`"chat"`) e `mode` (normalizado). Continua
redigido, escalar, `sort_keys`. Ex.:

```json
{"allowed": true, "blocked": false, "dry_run": true, "failure_code": null,
 "interface": "chat", "mode": "balanced", "persist_allowed": true,
 "private_mode": false, "would_execute": false, "would_write_audit": false}
```

## 7. Segurança preservada

- **Prompt nunca ecoado** (humano/JSON/erro) — testado após a migração.
- **Sem `result.to_dict()`** e sem `repr`/`vars`/`asdict` do resultado —
  testado por (a) monkeypatch de `CouncilOrchestrationResult.to_dict` para
  explodir (o `--json` continua funcionando) e (b) checagem AST no código.
- **JSON só de escalares seguros** — nenhum campo proibido (prompt/content/
  engine_id/secret/token/trace/audit_envelope) aparece.
- **Roteamento leve preservado**: mensagem não-`/conselho` → `None`;
  `/conselho simular` → dry-run; demais `/conselho` → fail-closed. O handler
  não captura mensagens que não começam com `/conselho`.
- **Sem contexto de kernel**: harness/policy/vault/audit reais nunca chamados —
  testes de regressão MC18 seguem verdes.
- **Leveza/pureza**: a migração não adicionou rede/subprocess/threading/
  asyncio/cloud/FS/env/relógio/aleatoriedade nem dependência nova (o chat
  passou a importar o helper puro e deixou de importar `json`) — provado por
  AST.

## 8. Testes adicionados/ajustados

| Arquivo | Testes |
|---|---|
| `tests/council/test_chat_conselho_dry_run.py` | +15 novos (total do arquivo: 50) |
| `tests/council/test_cli_conselho_dry_run.py` | 1 teste ajustado (não-migração → migração do chat) |

Novos (MC23): `test_chat_conselho_uses_safe_output_helper`,
`..._module_imports_safe_output_helper`, `..._json_uses_safe_output_shape`,
`..._json_contains_interface_and_mode`, `..._default_mode_json_balanced`,
`..._human_output_is_user_friendly`, `..._human_output_avoids_internal_jargon`,
`..._prompt_still_not_echoed_after_migration`,
`..._gate_blocked_safe_after_migration`, `..._denied_safe_after_migration`,
`..._exception_safe_after_migration`,
`..._non_command_still_returns_none_after_migration`,
`..._still_no_result_to_dict_after_migration`,
`..._module_no_result_dump_after_migration`, `test_cli_dry_run_untouched`.
Os 35 testes MC18/MC19 do arquivo do chat continuam verdes (regressão de
segurança).

## 9. O que NÃO foi feito

- sem migração/alteração do CLI (`cli_dry_run.py`/`cli.py` intocados)
- sem alteração do helper `safe_output.py`
- sem reconciliação das flags proibidas (o chat mantém as 10; a reconciliação
  8↔10 fica para MC24)
- sem motor real, cloud, subprocess, persistência
- sem policy/audit/vault reais
- sem alteração de `.github/`, `pyproject.toml`, `setup.cfg`
- sem tag, release ou PyPI

## 10. Validação final

| Item | Resultado |
|---|---|
| RUFF | PASS |
| PYTEST | PASS_952 (937 + 15 novos) |
| BUILD | PASS_IN_TMP_SANDBOX_FS_QUIRK |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | WARN (LOG_LEGACY_UNANCHORED, esperado) |
| COBERTURA (chat_dry_run.py) | 92% |
| GIT_FSCK | PASS |
| `git diff --name-only HEAD -- .github pyproject.toml setup.cfg` | vazio (NO_FORBIDDEN_DIFF=true) |
| `git diff --name-only HEAD -- cli_dry_run.py cli.py` | vazio (CLI_NOT_MIGRATED_IN_MC23=true) |
| `git diff --name-only HEAD -- safe_output.py` | vazio (SAFE_OUTPUT_UNCHANGED=true) |
| CI_STATUS | PASS |
| CI_JOBS | 17/17 |
| `git tag --points-at HEAD` | vazio (NO_NEW_TAG_ON_HEAD=true) |

## 11. Riscos remanescentes

- **Ambas as superfícies agora usam o helper** para segurança/estrutura/JSON —
  a duplicação de LÓGICA DE SEGURANÇA está eliminada. Resta duplicação de
  **texto humano** (CLI e chat têm frases próprias, por decisão de produto);
  unificar o texto, se desejado, seria uma decisão futura.
- **Divergência das flags proibidas** (8 na CLI, 10 no chat) permanece — o
  chat manteve as 10 nesta fase. Reconciliação reservada para MC24.
  **→ Resolvido em MC24 (decisão A):** CLI e chat passaram a compartilhar o
  mesmo conjunto de 10 via fonte única `src/nomos/council/forbidden_flags.py`
  (ver `docs/missions/MC24_FORBIDDEN_FLAGS_CONTRACT_RECONCILIATION.md`).
- **Contrato público do JSON do chat** mudou de 8 para 10 campos (adição
  compatível de `interface`/`mode`), alinhando com o CLI (MC22). Documentado
  aqui e no CHANGELOG.

## 12. Próximo passo recomendado

MC24 — Forbidden Flags Contract Reconciliation + UX Hardening: reconciliar o
conjunto de flags proibidas entre CLI (8) e chat (10) e endurecer as mensagens,
sem alterar execução real, agora que as duas superfícies compartilham o mesmo
helper de saída segura.
