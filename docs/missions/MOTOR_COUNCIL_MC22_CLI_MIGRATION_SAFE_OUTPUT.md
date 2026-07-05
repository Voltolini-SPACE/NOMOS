# MOTOR COUNCIL MC22 — CLI MIGRATION TO SHARED SAFE OUTPUT HELPER

## 1. Status final

STATUS_FINAL=PASS_MOTOR_COUNCIL_MC22_CLI_MIGRATION_SAFE_OUTPUT

O comando `nomos conselho simular` foi migrado para consumir o helper
compartilhado `src/nomos/council/safe_output.py`: a **estrutura segura** e o
**JSON** de saída agora vêm de `build_safe_output` + `render_json_output` (o
CLI não monta mais o JSON à mão e não lê o resultado do orquestrador além de
`allowed`/`blocked`/`failure_code`, isolado dentro do helper). Em paralelo, a
saída **humana** ficou mais simples e amigável para pessoas sem experiência
técnica, sem jargão e sem vazar nada. O Chat **não** foi migrado
(`chat_dry_run.py`/`amigavel.py` intocados) e o próprio helper
(`safe_output.py`) não foi alterado. 15 testes novos; suíte 922 → 937. Nenhuma
tag/release/PyPI; nenhum `.github/`, `pyproject.toml` ou `setup.cfg` alterado.

## 2. Baseline

| Item | Resultado |
|---|---|
| BASELINE_HEAD | a467ffb |
| BASELINE_TAG | v1.3.0rc4-motor-council-dry-run-21-ga467ffb |
| GIT_STATUS | CLEAN (antes das mudanças) |
| GIT_FSCK | PASS (1 commit dangling pré-existente, benigno) |
| RUFF | PASS |
| PYTEST | PASS_922 (antes) → PASS_937 (depois) |
| BUILD | PASS_IN_TMP_SANDBOX_FS_QUIRK |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | WARN (LOG_LEGACY_UNANCHORED, esperado) |

## 3. Escopo

```text
CLI_MIGRATED_TO_SAFE_OUTPUT=true
CHAT_MIGRATED=false
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
| `src/nomos/council/cli_dry_run.py` | migrado ao helper: importa `build_safe_output`/`render_json_output`; removeu o `_render_json` manual e o `import json`; o JSON agora sai de `render_json_output(build_safe_output(...))` (10 campos, Opção A); mensagens humanas trocadas por versões amigáveis; `_render_human` lê só o `CouncilSafeOutput` |
| `tests/council/test_cli_conselho_dry_run.py` | +15 testes (migração + UX + regressão de segurança); os 29 testes anteriores continuam verdes |
| `docs/missions/MOTOR_COUNCIL_MC22_CLI_MIGRATION_SAFE_OUTPUT.md` | este relatório |
| `docs/architecture/MOTOR_COUNCIL_INDEX_v1.md` | ponte: `SHARED_HELPER_ADOPTED_BY_CLI=true` |
| `CHANGELOG.md` | entrada `[Unreleased]` (Changed/Security/Not changed) |

**Não alterados** (confirmado por `git diff` vazio): `chat_dry_run.py`,
`amigavel.py`, `safe_output.py`, `cli.py`, `orchestrator.py`,
`local_harness.py`, `policy_gate.py`, `audit_envelope.py`, `.github/`,
`pyproject.toml`, `setup.cfg`.

## 5. UX simples (para pessoas sem experiência técnica)

A saída humana do CLL foi reescrita para ser clara e sem jargão:

**Sucesso:**

```text
[NOMOS-MC-DRY-RUN] Simulação segura concluída.
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
[NOMOS-MC-GATE-BLOCKED] A simulação foi bloqueada por segurança.
Nada foi executado.
Nada foi salvo.
O conteúdo bloqueado não será exibido.
```

**Opção não permitida / uso incorreto (sem ecoar a flag nem o texto):**

```text
[NOMOS-MC-CLI-DENIED] Este comando não pode ser usado com essa opção.
Nada foi executado.
Nada foi salvo.
```

(mensagens específicas e amigáveis também para modo inexistente e texto
ausente). O bloco técnico `DRY_RUN=true`/`REAL_*` fica sob "Status:" para quem
quiser conferir, e os detalhes técnicos completos continuam disponíveis no
`--json`. Um teste garante que a saída humana **não** contém jargão
(`orchestrator`, `envelope`, `payload`, `failure_code`, `to_dict`, etc.).

**Decisão de produto (registrada):** a segurança e o **JSON** são unificados no
helper (fonte única), mas o **texto humano** é específico do CLI e amigável —
porque as frases simples exigidas divergem dos textos canônicos do helper, e o
`safe_output.py` está fora do escopo de alteração desta missão. As mensagens
humanas leem **apenas** os campos escalares seguros do `CouncilSafeOutput`,
então continuam sem vazamento.

## 6. Contrato de JSON (Opção A adotada)

O `--json` do CLI passou de 8 para **10 campos** (adotando o formato do
helper): acrescentou `interface` (`"cli"`) e `mode` (normalizado:
`fast|balanced|critical|paranoid`). Continua redigido, montado só de escalares
seguros, `sort_keys`. Ex.:

```json
{"allowed": true, "blocked": false, "dry_run": true, "failure_code": null,
 "interface": "cli", "mode": "balanced", "persist_allowed": true,
 "private_mode": false, "would_execute": false, "would_write_audit": false}
```

## 7. Segurança preservada

- **Prompt nunca ecoado** (humano/JSON/erro) — testado após a migração.
- **Sem `result.to_dict()`** e sem `repr`/`vars`/`asdict` do resultado —
  testado por (a) monkeypatch de `CouncilOrchestrationResult.to_dict` para
  explodir (o `--json` continua funcionando) e (b) checagem AST no código.
- **JSON só de escalares seguros** — nenhum campo proibido (prompt/content/
  engine_id/secret/token/trace/audit_envelope) aparece.
- **Sem contexto de kernel**: `conselho` continua roteado antes de `_paths()`;
  `Vault`/`PolicyEngine`/`AuditLog` reais não são construídos; harness real
  nunca chamado — testes de regressão MC15 seguem verdes.
- **Leveza/pureza**: a migração não adicionou rede/subprocess/threading/
  asyncio/cloud/FS/env/relógio/aleatoriedade nem dependência nova (o CLI passou
  a importar o helper puro e deixou de importar `json`) — provado por AST.

## 8. Testes adicionados/ajustados

| Arquivo | Testes |
|---|---|
| `tests/council/test_cli_conselho_dry_run.py` | +15 novos (total do arquivo: 44) |

Novos (MC22): `test_cli_conselho_uses_safe_output_helper`,
`..._module_imports_safe_output_helper`, `..._json_uses_safe_output_shape`,
`..._json_contains_interface_and_mode`, `..._default_mode_json_balanced`,
`..._human_output_is_user_friendly`, `..._human_output_avoids_internal_jargon`,
`..._prompt_still_not_echoed_after_migration`,
`..._gate_blocked_safe_after_migration`, `..._denied_safe_after_migration`,
`..._exception_safe_after_migration`,
`..._still_no_result_to_dict_after_migration`,
`..._module_no_result_dump_after_migration`,
`..._json_no_forbidden_keys_after_migration`, `test_chat_dry_run_untouched`.
Os 29 testes MC15/MC18/MC19 do arquivo continuam verdes (regressão de
segurança).

## 9. O que NÃO foi feito

- sem migração do Chat (`chat_dry_run.py`/`amigavel.py` intocados)
- sem alteração do helper `safe_output.py`
- sem motor real, cloud, subprocess, persistência
- sem policy/audit/vault reais
- sem alteração de `.github/`, `pyproject.toml`, `setup.cfg`
- sem tag, release ou PyPI

## 10. Validação final

| Item | Resultado |
|---|---|
| RUFF | PASS |
| PYTEST | PASS_937 (922 + 15 novos) |
| BUILD | PASS_IN_TMP_SANDBOX_FS_QUIRK |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | WARN (LOG_LEGACY_UNANCHORED, esperado) |
| GIT_FSCK | PASS |
| `git diff --name-only HEAD -- .github pyproject.toml setup.cfg` | vazio (NO_FORBIDDEN_DIFF=true) |
| `git diff --name-only HEAD -- chat_dry_run.py amigavel.py safe_output.py` | vazio (CHAT_NOT_MIGRATED + helper intocado) |
| CI_STATUS | PASS |
| CI_JOBS | 17/17 |
| `git tag --points-at HEAD` | vazio (NO_NEW_TAG_ON_HEAD=true) |

## 11. Riscos remanescentes

- **Mudança de contrato público do JSON do CLI** (8 → 10 campos): quem
  consumia o JSON do CLI passa a ver `interface`/`mode`. É uma adição
  compatível (nenhuma chave removida), documentada aqui e no CHANGELOG, mas
  vale registrar como mudança de superfície pública.
- **Ainda há duplicação de texto humano** entre CLI e Chat (por decisão de
  produto, a UX humana é específica por superfície). A parte de segurança/
  estrutura/JSON já é unificada no helper; a unificação de texto, se desejada,
  seria uma decisão futura.
- A divergência das flags proibidas (8 na CLI, 10 no chat) permanece; segue
  reservada para a fase de hardening (após MC23).

## 12. Próximo passo recomendado

MC23 — Chat Migration to Shared Safe Output Helper: migrar **apenas** o
`chat_dry_run.py` para o helper (estrutura + JSON), sem alterar o CLI, com
regressão completa e mantendo a UX de chat amigável e o não-vazamento.
