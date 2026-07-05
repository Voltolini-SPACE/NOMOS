# MOTOR COUNCIL MC21 — SHARED REDACTION HELPER IMPLEMENTATION

## 1. Status final

STATUS_FINAL=PASS_MOTOR_COUNCIL_MC21_SHARED_REDACTION_HELPER_IMPLEMENTATION

Helper compartilhado de saída segura/redigida do Motor Council implementado de
forma **isolada** em `src/nomos/council/safe_output.py`, conforme a
especificação MC20. Ele transforma o resultado de um dry-run numa estrutura
`CouncilSafeOutput` que carrega **apenas** os 10 campos escalares permitidos e
renderiza saídas humanas/JSON redigidas por `interface` (`cli`/`chat`). 36
testes novos. A CLI (`cli_dry_run.py`) e o chat (`chat_dry_run.py`) **não**
foram migrados — seguem com o código próprio até MC22/MC23. Nenhuma
tag/release/PyPI; nenhum `.github/`, `pyproject.toml` ou `setup.cfg` alterado.

## 2. Baseline

| Item | Resultado |
|---|---|
| BASELINE_HEAD | 651fd9a |
| BASELINE_TAG | v1.3.0rc4-motor-council-dry-run-19-g651fd9a |
| GIT_STATUS | CLEAN (antes das mudanças) |
| GIT_FSCK | PASS (1 commit dangling pré-existente, benigno) |
| RUFF | PASS |
| PYTEST | PASS_886 (antes) → PASS_922 (depois) |
| BUILD | PASS_IN_TMP_SANDBOX_FS_QUIRK (wheel inclui `safe_output.py`) |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | WARN (LOG_LEGACY_UNANCHORED, esperado) |
| COBERTURA (safe_output.py) | 99% |

## 3. Escopo

```text
HELPER_IMPLEMENTED=true
CLI_MIGRATED=false
CHAT_MIGRATED=false
RUNTIME_BEHAVIOR_CHANGED=false
REAL_ENGINE_EXECUTION=false
REAL_POLICY=false
REAL_AUDIT=false
REAL_VAULT=false
PERSISTENCE=false
```

## 4. O que foi criado

| Arquivo | Papel |
|---|---|
| `src/nomos/council/safe_output.py` | módulo **puro** e isolado: `CouncilSafeOutput` (frozen dataclass, 10 escalares + `to_json_dict`), `build_safe_output(result, *, interface, mode, private_mode)`, `render_human_output`, `render_json_output`, `render_denied_output`, `render_gate_blocked_output`, `render_exception_output`, constante `SAFE_OUTPUT_INVALID_RESULT` |
| `tests/test_council_safe_output.py` | 36 testes (estrutura/JSON, não-uso de dump/repr, render humano por interface, não-vazamento, pureza AST) |
| `docs/missions/MOTOR_COUNCIL_MC21_SHARED_REDACTION_HELPER_IMPLEMENTATION.md` | este relatório |

Atualizados: `CHANGELOG.md`; pontes em
`docs/architecture/MOTOR_COUNCIL_SHARED_OUTPUT_REDACTION_SPEC_v1.md` e
`docs/architecture/MOTOR_COUNCIL_INDEX_v1.md`
(`SHARED_HELPER_IMPLEMENTED=true`).

Não tocados: `cli_dry_run.py`, `chat_dry_run.py`, `cli.py`, `amigavel.py`,
`orchestrator.py`, `local_harness.py`, `policy_gate.py`, `audit_envelope.py`.

## 5. API implementada

```python
@dataclass(frozen=True)
class CouncilSafeOutput:
    interface: Literal["cli", "chat"]
    dry_run: bool
    allowed: bool
    blocked: bool
    would_execute: bool
    would_write_audit: bool
    private_mode: bool
    persist_allowed: bool
    failure_code: str | None
    mode: str
    def to_json_dict(self) -> dict[str, object]: ...

def build_safe_output(result, *, interface, mode, private_mode) -> CouncilSafeOutput
def render_human_output(output) -> str
def render_json_output(output) -> str
def render_denied_output(interface, reason=None) -> str
def render_gate_blocked_output(interface) -> str
def render_exception_output(interface) -> str
```

`build_safe_output` lê do `result` **apenas** `allowed`/`blocked`/
`failure_code` via `getattr`; `dry_run=true`, `would_execute=false` e
`would_write_audit=false` são **travados por construção** (nunca lidos do
resultado); `persist_allowed = not private_mode`. `failure_code` de enum é
normalizado para o seu `.value`. `render_json_output` serializa **só** o
`to_json_dict()` — nunca o resultado inteiro.

## 6. Segurança

- **Campos permitidos (10)**: `interface`, `dry_run`, `allowed`, `blocked`,
  `would_execute`, `would_write_audit`, `private_mode`, `persist_allowed`,
  `failure_code`, `mode`. Nenhum outro. `interface ∈ {cli, chat}`; `mode`
  normalizado ∈ `{fast, balanced, critical, paranoid}`.
- **Nunca emite** prompt/content/final_content/candidate_content/engine_id/
  secret/token/api_key/authorization/bearer/trace/audit_envelope/candidate/
  raw_result — provado passando um `result` com esses campos "sujos" (valor
  `SEGREDO`) e conferindo que a saída não os contém.
- **Nunca serializa o resultado inteiro** nem chama métodos de dump/
  representação do resultado — provado por: (a) um `result` armadilha cujo
  método de serialização e a representação explodem se chamados, e
  (b) checagem AST no código-fonte de que os padrões de chamada
  (`.to_dict(`, `repr(`, `vars(`, `asdict`, `json.dumps(result`) não existem.
- **Fail-closed**: `result` sem o atributo `allowed` ⇒ saída bloqueada com
  `failure_code=SAFE_OUTPUT_INVALID_RESULT`, `would_execute=false`,
  `would_write_audit=false`. `interface`/`mode` inválidos ⇒ `ValueError` (não
  tenta corrigir texto).
- **Pureza (AST)**: não importa rede/subprocess/threading/asyncio/SDK cloud/
  motor, nem harness/orquestrador/CLI/chat/kernel reais; não toca FS/env; não
  usa relógio/aleatoriedade.

## 7. Testes adicionados

| Arquivo | Testes |
|---|---|
| `tests/test_council_safe_output.py` | 36 |

Cobre os 31 nomes exigidos pela missão (`test_safe_output_dataclass_is_frozen`,
`..._json_contains_only_safe_keys`, `..._json_cli_interface`,
`..._json_chat_interface`, `..._private_persist_false`,
`..._paranoid_mode_allowed`, `..._invalid_interface_rejected`,
`..._invalid_mode_rejected`, `..._invalid_result_fails_closed`,
`..._never_calls_result_to_dict`, `..._never_calls_result_repr`,
`..._never_uses_vars`, `..._human_cli_success`, `..._human_chat_success`,
`..._gate_blocked_cli`, `..._gate_blocked_chat`, `..._denied_cli`,
`..._denied_chat`, `..._exception_cli`, `..._exception_chat`,
`..._does_not_echo_prompt_like_fields`, `..._does_not_emit_content_fields`,
`..._does_not_emit_engine_id`, `..._does_not_emit_secret_token_api_key`,
`..._json_renderer_outputs_json_object`,
`..._json_renderer_does_not_include_raw_result`,
`..._module_does_not_import_network`,
`..._module_does_not_import_subprocess_threading_asyncio`,
`..._module_does_not_import_cloud_clients`,
`..._module_does_not_touch_filesystem_or_env`,
`..._module_does_not_use_time_or_random`) mais 5 extras
(`..._gate_blocked_via_human_render`, `..._failure_code_normalized_from_enum`,
`..._failure_code_normalized_from_plain_string`,
`..._module_does_not_import_council_runtime_or_kernel`,
`..._json_has_no_forbidden_substrings`).

## 8. O que NÃO foi feito

- sem migração da CLI (`cli_dry_run.py` intocado)
- sem migração do Chat (`chat_dry_run.py` intocado)
- sem alteração de `cli.py`/`amigavel.py`
- sem runtime novo (nenhum comando muda de comportamento)
- sem motor real, cloud, subprocess, persistência
- sem policy/audit/vault reais
- sem alteração de `.github/`, `pyproject.toml`, `setup.cfg`
- sem tag, release ou PyPI

## 9. Validação final

| Item | Resultado |
|---|---|
| RUFF | PASS |
| PYTEST | PASS_922 (886 + 36 novos) |
| BUILD | PASS_IN_TMP_SANDBOX_FS_QUIRK |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | WARN (LOG_LEGACY_UNANCHORED, esperado) |
| COBERTURA (safe_output.py) | 99% |
| GIT_FSCK | PASS |
| `git diff --name-only HEAD -- .github pyproject.toml setup.cfg` | vazio (NO_FORBIDDEN_DIFF=true) |
| `git diff --name-only HEAD -- cli_dry_run/chat_dry_run/cli.py/amigavel.py` | vazio (NO_CLI_CHAT_MIGRATION=true) |
| CI_STATUS | PASS |
| CI_JOBS | 17/17 |
| `git tag --points-at HEAD` | vazio (NO_NEW_TAG_ON_HEAD=true) |

## 10. Riscos remanescentes

- O helper **existe mas ainda não é usado** — enquanto a CLI e o chat não forem
  migrados (MC22/MC23), há três fontes do mesmo contrato (o helper + os dois
  módulos). O benefício (fonte única) só se materializa após a migração.
- A decisão de **adicionar** `interface`/`mode` ao JSON público continua em
  aberto: o helper os inclui (10 chaves), mas a CLI/chat hoje emitem 8. A
  migração (MC22/MC23) precisa decidir explicitamente se adota as 10 chaves
  (mudança de contrato público, com nota de CHANGELOG e testes) ou mantém as 8.
- A divergência das flags proibidas (8 na CLI, 10 no chat) permanece nos
  módulos atuais; sua reconciliação segue reservada para MC24.

## 11. Próximo passo recomendado

MC22 — CLI Migration to Shared Safe Output Helper: migrar **apenas** o
`cli_dry_run.py` para usar o helper, com regressão completa (os testes da CLI
devem continuar verdes, mudando só a fonte da saída) e **sem** tocar no chat
nem habilitar execução real.
