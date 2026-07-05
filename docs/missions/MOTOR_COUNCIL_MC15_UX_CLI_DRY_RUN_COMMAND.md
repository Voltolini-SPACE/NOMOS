# MOTOR COUNCIL MC15-UX — CLI DRY-RUN COMMAND

## 1. Status final

STATUS_FINAL=PASS_MOTOR_COUNCIL_MC15_UX_CLI_DRY_RUN_COMMAND

`nomos conselho simular "texto"` passa a existir como comando **dry-run**,
chamando **apenas** o `CouncilOrchestratorDryRun` e imprimindo um resultado
**redigido**. Todos os outros usos de `conselho` (raiz, `perguntar`,
`revisar`, `status`, `modos`, `diagnostico`, `explicar`, desconhecidos)
continuam DESABILITADOS/fail-closed. O prompt nunca é ecoado; nenhum motor
real, harness, policy/audit/vault real é chamado; `_paths()` não é construído;
flags proibidas falham fechado. 29 testes novos (mínimo exigido: 28). Suíte:
799 → 828. Nenhuma tag/release/PyPI; nenhum `.github/`, `pyproject.toml` ou
`setup.cfg` alterado.

## 2. Baseline

| Item | Resultado |
|---|---|
| BASELINE_HEAD | adfa006 |
| BASELINE_TAG | v1.3.0rc4-motor-council-dry-run-6-gadfa006 |
| GIT_STATUS | CLEAN (antes das mudanças) |
| GIT_FSCK | PASS (1 commit dangling pré-existente, benigno) |
| RUFF | PASS |
| PYTEST | PASS_799 (antes) → PASS_828 (depois) |
| BUILD | PASS_IN_TMP_SANDBOX_FS_QUIRK (wheel inclui `cli_dry_run.py`) |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | WARN (LOG_LEGACY_UNANCHORED, esperado) |

## 3. Escopo

```text
CLI_DRY_RUN_COMMAND=true
REAL_ENGINE_EXECUTION=false
REAL_POLICY=false
REAL_AUDIT=false
REAL_VAULT=false
PERSISTENCE=false
CHAT_COMMAND=false
```

## 4. O que foi criado

| Arquivo | Papel |
|---|---|
| `src/nomos/council/cli_dry_run.py` | novo módulo: `route_conselho(tokens)` (roteia só `simular` para dry-run; resto → `run_disabled`), `simular(tokens)` (parse manual de flags + prompt, chama só o orquestrador), render humano e JSON **redigidos**, mapa de modos pt→interno, flags proibidas |
| `src/nomos/cli.py` | **alterado**: o curto-circuito de `conselho` em `main()` agora chama `route_conselho(_argv[1:])` (ainda antes do argparse e de `_paths()`); `cmd_conselho` (fallback) também roteia; help do subparser menciona "só `simular` (dry-run), demais DESABILITADOS" |
| `tests/council/test_cli_conselho_dry_run.py` | 29 testes (comportamento + still-disabled + AST) |
| `tests/council/test_cli_conselho_disabled.py` | **2 testes MC14 repontados**: usavam `conselho simular` esperando "desabilitado"; como `simular` foi habilitado, passaram a usar `perguntar` (ainda desabilitado). Nenhuma garantia enfraquecida |

Não foram tocados: `orchestrator.py`, `local_harness.py`, `policy_gate.py`,
`audit_envelope.py`, `models.py`, nem qualquer módulo real de kernel. Não foi
alterado `.github/`, `pyproject.toml` ou `setup.cfg`.

## 5. Comportamento permitido

`nomos conselho simular "texto"` (+ flags `--modo`, `--privado`, `--json`,
`--iniciante`, `--avancado`):

- Constrói um `CouncilOrchestrationInput` (session_id fixo `cli-conselho-simular`,
  o prompt digitado, modo mapeado, private conforme flag) e chama
  `CouncilOrchestratorDryRun().run(entrada)`. O prompt **alimenta** o
  orquestrador, mas nunca é impresso/serializado.
- Modos: `rapido→fast`, `balanceado→balanced` (default), `critico→critical`,
  `paranoico→paranoid`. `paranoico` **implica** `private_mode=true`
  (`persist_allowed=false`). Modo inválido → fail-closed (sem ecoar o valor).
- Saída humana (permitido):

  ```text
  [NOMOS-MC-DRY-RUN] Motor Council simulado com sucesso.
  DRY_RUN=true
  REAL_ENGINE_EXECUTION=false
  REAL_POLICY=false
  REAL_AUDIT=false
  REAL_VAULT=false
  PERSISTENCE=false
  ```

- Saída humana (gate bloqueou):

  ```text
  [NOMOS-MC-GATE-BLOCKED] Resposta bloqueada pelo Policy Gate dry-run.
  Nada foi executado.
  Nada foi persistido.
  Conteúdo bloqueado não será exibido.
  ```

- Saída JSON (`--json`): payload **mínimo** montado só de escalares —
  `dry_run`, `allowed`, `blocked`, `would_execute` (false), `would_write_audit`
  (false), `private_mode`, `persist_allowed`, `failure_code`. Nunca serializa
  `trace`/`final_envelope`/`audit_result`, então não há como vazar
  prompt/conteúdo/engine_id. Em modo privado: `private_mode=true`,
  `persist_allowed=false`.

Exit codes: simulação concluída (permitida ou bloqueada pelo gate) → `0`; uso
indevido (flag proibida, modo inválido, texto ausente, exceção do orquestrador)
→ `3` (fail-closed).

## 6. Comportamento ainda bloqueado

Continuam retornando `[NOMOS-MC-CLI-DISABLED]` (via `run_disabled`, sem eco de
prompt):

```text
nomos conselho
nomos conselho perguntar "..."
nomos conselho revisar arquivo.md
nomos conselho status
nomos conselho modos
nomos conselho diagnostico
nomos conselho explicar
nomos conselho <qualquer-outro>
```

Flags proibidas em `simular` (`--real`, `--enable`, `--ativar`, `--force`,
`--unsafe`, `--cloud`, `--audit-real`, `--policy-real`) e qualquer flag
desconhecida → `[NOMOS-MC-CLI-DENIED]`, exit 3, sem ecoar o token nem o prompt.

## 7. Segurança

- **Não eco de prompt**: o prompt vai só para o orquestrador; nunca aparece em
  stdout (humano ou JSON), nem em mensagens de erro/denied (que usam texto
  fixo). Provado por `..._does_not_echo_prompt`, `..._json_redacted`,
  `..._invalid_mode_fails_closed`, `..._json_has_no_prompt_or_content_keys`.
- **Sem execução real**: `would_execute` e `would_write_audit` são sempre
  `false` (travados pelo próprio resultado do orquestrador). O
  `LocalExecutionHarness.execute` nunca é chamado (provado monkeypatchando-o
  para explodir: `..._does_not_call_harness_execute`).
- **Sem contexto sensível**: o roteamento de `conselho` acontece **antes** de
  `_paths()`, então Vault/PolicyEngine/AuditLog **não são construídos** para o
  comando (provado monkeypatchando `cli._paths` para explodir:
  `..._does_not_call_policy_vault_audit`, `..._does_not_construct_paths_for_simular`).
- **Só o orquestrador dry-run**: `cli_dry_run` importa o
  `CouncilOrchestratorDryRun` (dry-run puro, MC8) e nada real. AST prova que
  não importa rede/subprocess/threading/asyncio/SDK cloud/motor, nem
  `local_harness`/`kernel.policy`/`kernel.vault`/`kernel.audit`/router/
  cognição; e que não toca FS/env nem usa relógio/aleatoriedade.
- **Exceção fail-closed**: qualquer exceção do orquestrador vira
  `[NOMOS-MC-BLOCKED]` sem traceback nem prompt (`..._orchestrator_exception_fails_closed`).

## 8. Testes adicionados

| Arquivo | Testes |
|---|---|
| `tests/council/test_cli_conselho_dry_run.py` | 29 (10 do caminho `simular` permitido; 6 "ainda desabilitado"; 7 flags proibidas / não-chamada de camadas reais / JSON sem chaves proibidas / help / exceção; 6 de pureza AST) |

Cobre os 28 nomes exigidos pela missão. Observação de nomenclatura: os 5
testes AST usam o infixo `_dry_run_` (`test_cli_conselho_dry_run_module_does_not_import_network`
etc.) em vez do nome curto da lista, para não colidir com os testes AST
homônimos da MC14 (que cobrem `cli_disabled`) e deixar claro que estes cobrem
o módulo novo `cli_dry_run`. Todos os comportamentos exigidos estão presentes.
Além disso, 1 teste AST extra
(`..._module_does_not_import_real_kernel_or_harness`).

## 9. O que NÃO foi feito

- sem motor real (Ollama/llama.cpp/subprocess/HTTP)
- sem chat command
- sem cloud/rede
- sem policy/audit/vault reais (nem `_paths()`)
- sem harness de execução real
- sem persistência
- sem alteração de `.github/`, `pyproject.toml`, `setup.cfg`
- sem tag
- sem release
- sem PyPI

## 10. Validação final

| Item | Resultado |
|---|---|
| RUFF | PASS |
| PYTEST | PASS_828 (799 + 29 novos) |
| BUILD | PASS_IN_TMP_SANDBOX_FS_QUIRK |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | WARN (LOG_LEGACY_UNANCHORED, esperado) |
| GIT_FSCK | PASS |
| `git diff --name-only HEAD -- .github pyproject.toml setup.cfg` | vazio (NO_FORBIDDEN_DIFF=true) |
| CI_STATUS | PASS |
| CI_JOBS | 17/17 |
| `git tag --points-at HEAD` | vazio (NO_NEW_TAG_ON_HEAD=true) |

## 11. Riscos remanescentes

- O `simular` sempre usa `risk_level=A1` e `contains_sensitive_data=False` (o
  contrato não expõe esses ao usuário nesta fase, e o prompt não é
  inspecionado por design). Logo, pelo caminho normal da CLI, o resultado é
  quase sempre `allowed`. Os caminhos "bloqueado pelo gate" / "dado sensível"
  são exercitados por teste injetando um resultado bloqueado — a CLI os
  renderiza com segurança, mas não há hoje um flag de usuário que os force.
  Isso é intencional (sem inspeção de prompt), mas vale registrar.
- O `route_conselho` usa `tokens[0] == "simular"`. Um futuro alias (ex.:
  `simulate`) precisará ser adicionado explicitamente; hoje só `simular` é
  reconhecido, o resto cai no desabilitado.
- A constante `MOTOR_COUNCIL_CLI_ENABLED` (MC14) continua `False` e **não** é
  consultada por `simular` — o `simular` roda o orquestrador dry-run
  independentemente dela. Ou seja, "ligar" essa constante não muda nada; a
  habilitação de `simular` é por roteamento explícito, não por flag global.
  (Coerente com a filosofia: habilitação vem de código revisado, não de flip
  de flag.)

## 12. Próximo passo recomendado

MC16-UX — Chat Command SPEC/DISABLED: desenhar e registrar `/conselho` como
bloqueado/fail-closed (espelhando o esqueleto desabilitado da CLI), sem
executar o orquestrador ainda e sem ecoar prompt.
