# MOTOR COUNCIL MC16-UX — CHAT COMMAND SPEC/DISABLED

## 1. Status final

STATUS_FINAL=PASS_MOTOR_COUNCIL_MC16_UX_CHAT_COMMAND_DISABLED

O chat command `/conselho` passa a existir (aparece no `/ajuda` do chat
amigável), mas nasce **desabilitado/fail-closed** — mesma filosofia da CLI na
MC14. Qualquer uso (`/conselho`, `/conselho simular ...`, `/conselho
perguntar ...`, etc.) devolve uma mensagem genérica de bloqueio que declara
`CHAT_ENABLED=false` e nunca ecoa o texto do usuário. O handler é um módulo
puro que não chama o orquestrador, o harness, nem policy/audit/vault reais.
23 testes novos (mínimo exigido: 18). Suíte: 828 → 851. Nenhuma tag/release/
PyPI; nenhum `.github/`, `pyproject.toml` ou `setup.cfg` alterado.

## 2. Baseline

| Item | Resultado |
|---|---|
| BASELINE_HEAD | 3bee9f0 |
| BASELINE_TAG | v1.3.0rc4-motor-council-dry-run-8-g3bee9f0 |
| GIT_STATUS | CLEAN (antes das mudanças) |
| GIT_FSCK | PASS (1 commit dangling pré-existente, benigno) |
| RUFF | PASS |
| PYTEST | PASS_828 (antes) → PASS_851 (depois) |
| BUILD | PASS_IN_TMP_SANDBOX_FS_QUIRK (wheel inclui `chat_disabled.py`) |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | WARN (LOG_LEGACY_UNANCHORED, esperado) |
| COBERTURA | 86% geral (acima da meta 80% do CI) |

## 3. Escopo

```text
CHAT_COMMAND_SKELETON=true
CHAT_ENABLED=false
REAL_ENGINE_EXECUTION=false
REAL_POLICY=false
REAL_AUDIT=false
REAL_VAULT=false
PERSISTENCE=false
CLI_CHANGED=false
```

`CLI_CHANGED=false`: os comandos de CLI da MC14/MC15 (`nomos conselho`,
`nomos conselho simular`) não foram tocados. A única alteração de runtime fora
do módulo novo é a adição de um ramo `/conselho` ao loop do chat amigável
(`amigavel.py`) e uma linha no texto de ajuda.

## 4. O que foi criado

| Arquivo | Papel |
|---|---|
| `src/nomos/council/chat_disabled.py` | módulo **puro**: constante literal `MOTOR_COUNCIL_CHAT_ENABLED = False`, `CHAT_DISABLED_CODE`, `COMMAND="/conselho"`, `FUTURE_SUBCOMMANDS`, `is_conselho_command(msg)`, `disabled_message()` e `handle_disabled_chat_command(msg) -> str | None` (bloqueio genérico para `/conselho ...`; `None` para o resto) |
| `src/nomos/simple/amigavel.py` | **alterado** minimamente: ramo `/conselho` no loop de chat que delega ao handler puro; uma linha no bloco `AJUDA` |
| `tests/council/test_chat_conselho_disabled.py` | 23 testes (comportamento + integração pelo loop real + AST) |

Não foram tocados: `orchestrator.py`, `local_harness.py`, `policy_gate.py`,
`audit_envelope.py`, `cli.py`, `cli_disabled.py`, `cli_dry_run.py`, nem
qualquer módulo real de kernel. Não foi alterado `.github/`, `pyproject.toml`
ou `setup.cfg`.

## 5. Comportamento fail-closed

`handle_disabled_chat_command(message)`:

- `/conselho`, `/conselho simular <texto>`, `/conselho perguntar <texto>`,
  `/conselho revisar <arquivo>`, `/conselho status`, `/conselho modos`,
  `/conselho explicar`, `/conselho <qualquer-outro>` e qualquer variação com
  flags proibidas (`--real`, `--enable`, `--ativar`, `--force`, `--unsafe`,
  `--cloud`, `--audit-real`, `--policy-real`) → sempre devolve:

  ```text
  [NOMOS-MC-CHAT-DISABLED] Motor Council Chat ainda não está habilitado.

  Status:
    CHAT_ENABLED=false
    REAL_ENGINE_EXECUTION=false
    REAL_POLICY=false
    REAL_AUDIT=false
    REAL_VAULT=false
    PERSISTENCE=false

  O Motor Council está em dry-run/pre-release. No chat, nada é executado,
  nenhum prompt é processado e nada é gravado. Use a documentação do RC4,
  ou (fora do chat) o comando de terminal de simulação dry-run.
  ```

  O texto após o comando **nunca** aparece na resposta (a mensagem é uma
  constante, sem interpolação de entrada).

- **Mensagem não relacionada** (não começa com `/conselho`, inclui string
  vazia, `/conselhoxyz` coladinho, ou tipos não-string) → devolve `None`.
  **Escolha documentada**: `None` (não `""`), porque o loop do chat amigável
  só imprime quando o handler devolve uma resposta; devolver `None` deixa a
  mensagem seguir o fluxo normal do chat, sem o Council interferir.

Integração no chat amigável (`amigavel.iniciar_chat`): o ramo
`if linha == "/conselho" or linha.startswith("/conselho "):` delega ao handler
e imprime o bloqueio, **antes** de qualquer processamento por motor. Coberto
por um teste que dirige o loop real (`test_chat_conselho_disabled_via_amigavel`).

## 6. Testes adicionados

| Arquivo | Testes |
|---|---|
| `tests/council/test_chat_conselho_disabled.py` | 23 (15 de comportamento do handler; 1 de "sem API de habilitação"; 1 de integração pelo loop real do chat; 6 de pureza AST) |

Cobre os 20 nomes listados na missão (mínimo 18): `test_chat_conselho_disabled_root`,
`test_chat_conselho_simular_disabled`, `test_chat_conselho_perguntar_disabled`,
`test_chat_conselho_revisar_disabled`, `test_chat_conselho_status_disabled`,
`test_chat_conselho_modos_disabled`, `test_chat_conselho_unknown_disabled`,
`test_chat_conselho_does_not_echo_prompt`,
`test_chat_conselho_forbidden_flags_do_not_enable`,
`test_chat_conselho_output_declares_no_real_execution`,
`test_chat_conselho_no_env_enable`,
`test_chat_conselho_does_not_call_orchestrator`,
`test_chat_conselho_does_not_call_harness`,
`test_chat_conselho_does_not_call_policy_vault_audit`,
`test_chat_conselho_non_command_ignored`,
`test_chat_conselho_module_does_not_import_network`,
`test_chat_conselho_module_does_not_import_subprocess_threading_asyncio`,
`test_chat_conselho_module_does_not_import_cloud_clients`,
`test_chat_conselho_module_does_not_touch_filesystem_or_env`,
`test_chat_conselho_module_does_not_use_time_or_random` — mais 3 extras:
`..._no_enable_api`, `..._disabled_via_amigavel` (integração),
`..._module_does_not_import_council_or_kernel_runtime`.

## 7. O que NÃO foi feito

- sem execução real
- sem orquestrador chamado (`CouncilOrchestratorDryRun.run` nunca invocado)
- sem chat funcional (o comando só informa que está desabilitado)
- sem motor / Ollama / subprocess / HTTP / cloud
- sem persistência
- sem policy/audit/vault reais
- sem alteração de `.github/`, `pyproject.toml`, `setup.cfg`
- sem alteração dos comandos de CLI (MC14/MC15)
- sem tag
- sem release
- sem PyPI

## 8. Validação final

| Item | Resultado |
|---|---|
| RUFF | PASS |
| PYTEST | PASS_851 (828 + 23 novos) |
| BUILD | PASS_IN_TMP_SANDBOX_FS_QUIRK |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | WARN (LOG_LEGACY_UNANCHORED, esperado) |
| COBERTURA | 86% (≥ 80%) |
| GIT_FSCK | PASS |
| `git diff --name-only HEAD -- .github pyproject.toml setup.cfg` | vazio (NO_FORBIDDEN_DIFF=true) |
| CI_STATUS | PASS |
| CI_JOBS | 17/17 |
| `git tag --points-at HEAD` | vazio (NO_NEW_TAG_ON_HEAD=true) |

## 9. Riscos remanescentes

- A constante `MOTOR_COUNCIL_CHAT_ENABLED` é `False` e o handler **não a
  consulta** (é incondicionalmente bloqueado, defesa em profundidade). "Ligar"
  a constante sozinha não habilita nada — a habilitação real virá de código
  novo e revisado (MC17-UX+), não de flip de flag.
- O ramo de integração usa `linha == "/conselho" or linha.startswith(
  "/conselho ")`. `/conselhoxyz` (coladinho) não casa e cairia no fluxo normal
  do chat (tratado como texto). É o comportamento pretendido, mas vale
  registrar.
- O chat amigável (`amigavel.py`) é só uma das superfícies de chat; se no
  futuro houver outra superfície (ex.: um chat headless), ela também precisará
  rotear `/conselho` para o handler desabilitado até a habilitação real.

## 10. Próximo passo recomendado

MC17-UX — Chat Dry-run Command SPEC/IMPLEMENTATION PLAN: desenhar
`/conselho simular` chamando o `CouncilOrchestratorDryRun` (espelhando o que a
CLI já faz em `nomos conselho simular`), com plano de implementação e testes,
antes de qualquer habilitação funcional — mantendo o não-eco de prompt e o
resto do namespace `/conselho` fail-closed.
