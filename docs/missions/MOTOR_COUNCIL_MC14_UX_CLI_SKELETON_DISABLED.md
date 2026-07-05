# MOTOR COUNCIL MC14-UX — CLI SKELETON DISABLED

## 1. Status final

STATUS_FINAL=PASS_MOTOR_COUNCIL_MC14_UX_CLI_SKELETON_DISABLED

O comando `nomos conselho` passa a existir e aparece no `--help`, mas nasce
**desabilitado por construção** (fail-closed). Qualquer uso — com ou sem
subcomando, prompt ou flag — devolve uma mensagem genérica de bloqueio,
declara explicitamente que nada real é executado, e retorna sem chamar o
orquestrador, o harness de execução real, ou policy/audit/vault reais, sem
persistir nada e sem ecoar o que o usuário digitou. 21 testes novos (mínimo
exigido: 15). Suíte: 778 → 799. Nenhuma tag, release ou PyPI; nenhum
`.github/`, `pyproject.toml` ou `setup.cfg` alterado.

## 2. Baseline

| Item | Resultado |
|---|---|
| BASELINE_HEAD | 813c601 |
| BASELINE_TAG | v1.3.0rc4-motor-council-dry-run-4-g813c601 |
| GIT_STATUS | CLEAN (antes das mudanças) |
| GIT_FSCK | PASS (1 commit dangling pré-existente, benigno) |
| RUFF | PASS |
| PYTEST | PASS_778 (antes) → PASS_799 (depois) |
| BUILD | PASS_IN_TMP_SANDBOX_FS_QUIRK (wheel inclui `nomos/council/cli_disabled.py`) |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | WARN (LOG_LEGACY_UNANCHORED, esperado) |

## 3. Escopo

```text
CLI_SKELETON=true
CLI_ENABLED=false
REAL_ENGINE_EXECUTION=false
REAL_POLICY=false
REAL_AUDIT=false
REAL_VAULT=false
PERSISTENCE=false
```

## 4. O que foi criado

| Arquivo | Papel |
|---|---|
| `src/nomos/council/cli_disabled.py` | módulo **puro** do CLI desabilitado: constante literal `MOTOR_COUNCIL_CLI_ENABLED = False`, `DISABLED_EXIT_CODE = 0`, `DISABLED_CODE`, `FUTURE_SUBCOMMANDS`, `disabled_message()` e `run_disabled(args=None)` (ignora `args`, imprime a mensagem genérica, retorna 0) |
| `src/nomos/cli.py` | **alterado** minimamente: (a) registra o subparser `conselho` no `build_parser()` (para aparecer no `--help`), com `nargs=REMAINDER` e `fn=cmd_conselho` como defesa em profundidade; (b) `cmd_conselho(ctx, args)` delega a `run_disabled()` ignorando `ctx`/`args`; (c) `main()` **curto-circuita** `conselho` antes do argparse e de `_paths()` |
| `tests/council/test_cli_conselho_disabled.py` | 21 testes (comportamento + AST) |

Não foram tocados: `orchestrator.py`, `local_harness.py`, `policy_gate.py`,
`audit_envelope.py`, nem qualquer outro módulo do Council core. Não foi
alterado `.github/`, `pyproject.toml` ou `setup.cfg` — o entry-point
`nomos = nomos.cli:main` já existia, então registrar o subcomando dentro do
`cli.py` existente bastou.

## 5. Comportamento fail-closed

`nomos conselho` (e qualquer variação: `conselho status`, `conselho modos`,
`conselho simular "x"`, `conselho perguntar "x"`, subcomando desconhecido,
com flags `--enable`/`--ativar`/`--force`/`--real`/`--executar`/`--unsafe`/
`--cloud`) sempre imprime:

```text
[NOMOS-MC-CLI-DISABLED] Motor Council CLI ainda não está habilitado.

Status:
  CLI_ENABLED=false
  REAL_ENGINE_EXECUTION=false
  REAL_POLICY=false
  REAL_AUDIT=false
  REAL_VAULT=false
  PERSISTENCE=false

O Motor Council está em dry-run/pre-release. Nada é executado, nenhum
prompt é processado e nada é gravado. Use apenas a documentação do RC4
por enquanto:
  docs/architecture/MOTOR_COUNCIL_INDEX_v1.md
  docs/architecture/MOTOR_COUNCIL_UX_SPEC_v1.md
```

Exit code: `0` (informativo — rodar o comando e receber "está desabilitado"
é um sucesso operacional, como `nomos status`/`nomos doutor`; o projeto não
tem um código específico para "indisponível", e `0` está entre os valores
permitidos pela missão). Escolha registrada explicitamente.

Garantias-chave (provadas por teste):

- **Curto-circuito em `main()`**: se `argv[0] == "conselho"`, o handler
  desabilitado é chamado **antes** do argparse e **antes** de `_paths()` —
  logo nenhum subcomando/prompt/flag é interpretado e **nenhum contexto de
  kernel (Vault/PolicyEngine/AuditLog) é sequer construído**
  (`test_cli_conselho_does_not_call_policy_vault_audit` monkeypatcha
  `cli._paths` para explodir e o comando continua funcionando).
- **Prompt nunca ecoado**: o conteúdo digitado não aparece em stdout
  (`test_cli_conselho_perguntar_does_not_echo_prompt`,
  `..._simular_...`, `..._json_if_supported_is_redacted`,
  `..._unknown_subcommand_fail_closed`).
- **Flags não habilitam**: nenhuma das 7 flags perigosas muda o resultado
  (`test_cli_conselho_flags_cannot_enable`).
- **Orquestrador/harness nunca chamados**: monkeypatch de
  `CouncilOrchestratorDryRun.run` e `LocalExecutionHarness.execute` para
  explodir; o comando não os toca
  (`..._does_not_call_orchestrator`, `..._does_not_call_harness`).
- **Env não liga**: setar `MOTOR_COUNCIL_CLI_ENABLED=1` (e afins) no ambiente
  não altera nada; a constante continua `False` (`..._no_env_enable`).
- **Sem persistência**: rodar o comando num `NOMOS_HOME` limpo não cria
  nenhum arquivo (`..._no_persistence`).
- **`--help` anuncia o estado**: a linha do `conselho` no `nomos --help` diz
  "pré-release, ainda DESABILITADO" (`..._help_mentions_disabled_or_prerelease`).

## 6. Testes adicionados

| Arquivo | Testes |
|---|---|
| `tests/council/test_cli_conselho_disabled.py` | 21 (14 de comportamento + 7 de pureza/AST) |

Cobre os 17 nomes exigidos pela missão: `test_cli_conselho_disabled`,
`test_cli_conselho_status_disabled`,
`test_cli_conselho_perguntar_does_not_echo_prompt`,
`test_cli_conselho_simular_does_not_echo_prompt`,
`test_cli_conselho_flags_cannot_enable`,
`test_cli_conselho_output_declares_no_real_execution`,
`test_cli_conselho_does_not_call_orchestrator`,
`test_cli_conselho_does_not_call_harness`,
`test_cli_conselho_does_not_call_policy_vault_audit`,
`test_cli_conselho_no_env_enable`, `test_cli_conselho_no_persistence`,
`test_cli_conselho_help_mentions_disabled_or_prerelease`,
`test_cli_conselho_json_if_supported_is_redacted`,
`test_cli_conselho_unknown_subcommand_fail_closed`,
`test_cli_conselho_module_does_not_import_network`,
`test_cli_conselho_module_does_not_import_subprocess_threading_asyncio`,
`test_cli_conselho_module_does_not_import_cloud_clients` — mais 4 extras:
`..._module_does_not_import_council_runtime`,
`..._module_does_not_touch_filesystem_or_env`,
`..._module_does_not_use_time_or_random`,
`..._module_has_no_enable_api`.

## 7. O que NÃO foi feito

- sem execução real
- sem orquestrador real chamado (`CouncilOrchestratorDryRun.run` nunca invocado)
- sem CLI funcional (o comando só informa que está desabilitado)
- sem chat command
- sem motor / Ollama / subprocess / HTTP / cloud
- sem persistência
- sem policy/audit/vault reais
- sem alteração de `.github/`, `pyproject.toml`, `setup.cfg`
- sem tag
- sem release
- sem PyPI

## 8. Validação final

| Item | Resultado |
|---|---|
| RUFF | PASS |
| PYTEST | PASS_799 (778 + 21 novos) |
| BUILD | PASS_IN_TMP_SANDBOX_FS_QUIRK |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | WARN (LOG_LEGACY_UNANCHORED, esperado) |
| GIT_FSCK | PASS |
| `git diff --name-only HEAD -- .github pyproject.toml setup.cfg` | vazio (NO_FORBIDDEN_DIFF=true) |
| CI_STATUS | PASS |
| CI_JOBS | 17/17 |
| `git tag --points-at HEAD` | vazio (NO_NEW_TAG_ON_HEAD=true) |

## 9. Riscos remanescentes

- O curto-circuito em `main()` usa `argv[0] == "conselho"`. Se, numa fase
  futura, `conselho` ganhar um alias (ex.: `council`), o alias precisará ser
  incluído no curto-circuito **ou** dependerá apenas do fallback via
  `cmd_conselho` (que também está protegido). Hoje só `conselho` existe.
- O handler `run_disabled()` ignora `args` por design; quando a MC15-UX
  ligar o dry-run, será preciso trocar esse curto-circuito por um roteamento
  real de subcomando (`simular` → `CouncilOrchestratorDryRun`), com muito
  cuidado para manter o não-eco de prompt e o fail-closed dos demais
  subcomandos.
- A constante `MOTOR_COUNCIL_CLI_ENABLED` existe e é `False`, mas o
  comportamento não a consulta em runtime (o `run_disabled` é
  incondicionalmente bloqueado). Isso é intencional (defesa em profundidade),
  mas significa que "flipar" a constante sozinha não habilita nada — a
  habilitação real virá de código novo e revisado na MC15-UX, não de mudar
  esse literal.

## 10. Próximo passo recomendado

MC15-UX — CLI Dry-run Command: permitir que **apenas** `nomos conselho simular`
chame o `CouncilOrchestratorDryRun` (dry-run, sem motor real, sem
persistência), mantendo todos os outros subcomandos e o `conselho` raiz ainda
fail-closed, e preservando o não-eco de prompt.
