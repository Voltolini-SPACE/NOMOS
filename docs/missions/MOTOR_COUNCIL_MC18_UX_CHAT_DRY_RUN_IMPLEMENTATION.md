# MOTOR COUNCIL MC18-UX — CHAT DRY-RUN IMPLEMENTATION

## 1. Status final

STATUS_FINAL=PASS_MOTOR_COUNCIL_MC18_UX_CHAT_DRY_RUN_IMPLEMENTATION

`/conselho simular <texto>` passa a existir no chat como comando **dry-run**,
chamando **apenas** o `CouncilOrchestratorDryRun` e devolvendo uma resposta
**redigida** — espelhando o padrão seguro da CLI (MC15). Todos os outros usos
de `/conselho` (raiz, `perguntar`, `revisar`, `status`, `modos`, `explicar`,
`diagnostico`, desconhecidos) continuam DESABILITADOS/fail-closed, e mensagens
não-`/conselho` continuam devolvendo `None`. O prompt nunca é ecoado; o JSON é
montado à mão com escalares seguros (nunca `result.to_dict()`); nenhum motor
real, harness, policy/audit/vault real é chamado. 33 testes novos (mínimo
exigido: 32). Suíte: 851 → 884. Nenhuma tag/release/PyPI; nenhum `.github/`,
`pyproject.toml` ou `setup.cfg` alterado.

## 2. Baseline

| Item | Resultado |
|---|---|
| BASELINE_HEAD | 54b72be |
| BASELINE_TAG | v1.3.0rc4-motor-council-dry-run-12-g54b72be |
| GIT_STATUS | CLEAN (antes das mudanças) |
| GIT_FSCK | PASS (1 commit dangling pré-existente, benigno) |
| RUFF | PASS |
| PYTEST | PASS_851 (antes) → PASS_884 (depois) |
| BUILD | PASS_IN_TMP_SANDBOX_FS_QUIRK (wheel inclui `chat_dry_run.py`) |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | WARN (LOG_LEGACY_UNANCHORED, esperado) |
| COBERTURA | 86% geral (acima da meta 80% do CI) |

## 3. Escopo

```text
CHAT_DRY_RUN_ENABLED=true
REAL_ENGINE_EXECUTION=false
REAL_POLICY=false
REAL_AUDIT=false
REAL_VAULT=false
PERSISTENCE=false
```

## 4. O que foi criado

| Arquivo | Papel |
|---|---|
| `src/nomos/council/chat_dry_run.py` | novo módulo: `handle_chat_dry_run(message) -> str \| None` (roteia só `simular` → dry-run; resto de `/conselho` → `chat_disabled.disabled_message`; não-comando → `None`), `_simular(tokens)` (parse manual de flags + prompt, chama só o orquestrador), render humano/JSON **redigidos**, mapa de modos pt→interno, flags proibidas |
| `src/nomos/simple/amigavel.py` | **alterado**: o ramo `/conselho` do loop agora delega a `handle_chat_dry_run` (antes era `handle_disabled_chat_command`) |
| `tests/council/test_chat_conselho_dry_run.py` | 33 testes (comportamento + still-disabled + integração pelo loop real + AST) |
| `tests/council/test_chat_conselho_disabled.py` | **1 teste MC16 repontado**: `test_chat_conselho_disabled_via_amigavel` usava `/conselho simular` esperando "desabilitado"; como `simular` foi habilitado, passou a usar `perguntar` (ainda desabilitado). Nenhuma garantia enfraquecida |

Não foram tocados: `orchestrator.py`, `local_harness.py`, `policy_gate.py`,
`audit_envelope.py`, `chat_disabled.py`, `cli.py`, `cli_disabled.py`,
`cli_dry_run.py`, nem qualquer módulo real de kernel. Não foi alterado
`.github/`, `pyproject.toml` ou `setup.cfg`. O módulo puro
`chat_disabled.py` (MC16) segue intacto — o roteamento para dry-run vive no
módulo novo, e `chat_disabled` continua sendo a fonte da mensagem desabilitada.

## 5. Comportamento permitido

`/conselho simular <texto>` (+ flags `--modo`, `--privado`, `--json`,
`--iniciante`, `--avancado`):

- Constrói um `CouncilOrchestrationInput` (session_id fixo
  `chat-conselho-simular`, o prompt digitado, modo mapeado, private conforme
  flag) e chama `CouncilOrchestratorDryRun().run(entrada)`. O prompt
  **alimenta** o orquestrador, mas nunca é impresso/serializado.
- Modos: `rapido→fast`, `balanceado→balanced` (default), `critico→critical`,
  `paranoico→paranoid`. `paranoico` **implica** `private_mode=true`
  (`persist_allowed=false`). Modo inválido → fail-closed (sem ecoar o valor).
- Saída humana (permitido):

  ```text
  [NOMOS-MC-CHAT-DRY-RUN] Conselho simulado com segurança.
  DRY_RUN=true
  REAL_ENGINE_EXECUTION=false
  REAL_POLICY=false
  REAL_AUDIT=false
  REAL_VAULT=false
  PERSISTENCE=false
  ```

- Saída humana (gate bloqueou):

  ```text
  [NOMOS-MC-CHAT-GATE-BLOCKED] Resposta bloqueada pelo Policy Gate dry-run.
  Nada foi executado.
  Nada foi persistido.
  Conteúdo bloqueado não será exibido.
  ```

- Saída JSON (`--json`): payload **mínimo** escalar
  (`dry_run/allowed/blocked/would_execute/would_write_audit/private_mode/
  persist_allowed/failure_code`), montado à mão. Em modo privado:
  `private_mode=true`, `persist_allowed=false`.

Como handler de chat, devolve **strings** (o loop faz `say(...)`), não imprime.

## 6. Comportamento ainda bloqueado

Continuam devolvendo `[NOMOS-MC-CHAT-DISABLED]` (via
`chat_disabled.disabled_message`, sem eco de prompt):

```text
/conselho
/conselho perguntar ...
/conselho revisar ...
/conselho status
/conselho modos
/conselho explicar
/conselho diagnostico
/conselho <qualquer-outro>
```

Flags proibidas em `simular` (`--real`, `--enable`, `--ativar`, `--force`,
`--unsafe`, `--cloud`, `--audit-real`, `--policy-real`, `--vault-real`,
`--engine-real`) e qualquer flag desconhecida → `[NOMOS-MC-CHAT-DENIED]`, sem
ecoar o token nem o prompt. Mensagem que não começa com `/conselho` → `None`.

## 7. Segurança

- **Não eco de prompt**: o prompt vai só para o orquestrador; nunca aparece em
  resposta humana, JSON ou mensagem de erro/denied (que usam texto fixo).
- **Só o orquestrador dry-run**: `chat_dry_run` importa o
  `CouncilOrchestratorDryRun` (dry-run puro, MC8) e o `chat_disabled`; nada
  real. `LocalExecutionHarness.execute` nunca é chamado (provado
  monkeypatchando-o para explodir).
- **Sem kernel real**: os testes monkeypatcham `Vault`/`PolicyEngine`/
  `AuditLog` para explodir e o comando continua funcionando — nenhum é
  construído para o `simular`.
- **Nunca `result.to_dict()`**: o JSON é montado à mão a partir de escalares;
  um teste monkeypatcha `CouncilOrchestrationResult.to_dict` para explodir e o
  `--json` continua funcionando; outro teste confirma que a string `to_dict`
  nem aparece no código-fonte do módulo.
- **AST**: prova que o módulo não importa rede/subprocess/threading/asyncio/
  SDK cloud/motor, nem `local_harness`/`kernel.policy`/`kernel.vault`/
  `kernel.audit`/router/cognição; não toca FS/env; não usa relógio/
  aleatoriedade.
- **Exceção fail-closed**: qualquer exceção do orquestrador vira
  `[NOMOS-MC-CHAT-BLOCKED]` sem traceback nem prompt.

## 8. Testes adicionados

| Arquivo | Testes |
|---|---|
| `tests/council/test_chat_conselho_dry_run.py` | 33 (10 do `simular` permitido; 6 "ainda desabilitado"; 6 flags/não-comando/camadas reais/`to_dict`/JSON-keys/humano-sem-conteúdo/exceção; 2 de integração pelo loop real; 6 de pureza AST; +3 extras: sem-kernel, `to_dict`-runtime, `to_dict`-source) |

Cobre os 32 nomes exigidos pela missão. Ajuste MC16: o único teste que
dirigia o loop real com `/conselho simular` esperando "desabilitado"
(`test_chat_conselho_disabled_via_amigavel`) foi repontado para `perguntar`,
já que `simular` agora roda dry-run — nenhuma garantia enfraquecida (os testes
MC16 que chamam o handler **puro** `handle_disabled_chat_command` seguem
válidos, pois esse módulo não mudou).

## 9. O que NÃO foi feito

- sem motor real (Ollama/llama.cpp/subprocess/HTTP)
- sem cloud/rede
- sem persistência
- sem policy/audit/vault reais (nem `_paths()`)
- sem harness de execução real
- sem `result.to_dict()`
- sem alteração de `.github/`, `pyproject.toml`, `setup.cfg`
- sem alteração dos comandos de CLI (MC14/MC15) nem do `chat_disabled` (MC16)
- sem tag
- sem release
- sem PyPI

## 10. Validação final

| Item | Resultado |
|---|---|
| RUFF | PASS |
| PYTEST | PASS_884 (851 + 33 novos) |
| BUILD | PASS_IN_TMP_SANDBOX_FS_QUIRK |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | WARN (LOG_LEGACY_UNANCHORED, esperado) |
| COBERTURA | 86% (≥ 80%) |
| GIT_FSCK | PASS |
| `git diff --name-only HEAD -- .github pyproject.toml setup.cfg` | vazio (NO_FORBIDDEN_DIFF=true) |
| CI_STATUS | PASS |
| CI_JOBS | 17/17 |
| `git tag --points-at HEAD` | vazio (NO_NEW_TAG_ON_HEAD=true) |

## 11. Riscos remanescentes

- Como no CLI (MC15), o `simular` do chat usa `risk_level=A1` e
  `contains_sensitive_data=False` (não expostos ao usuário; o prompt não é
  inspecionado por design). Logo, o caminho normal quase sempre é `allowed`;
  os caminhos "bloqueado pelo gate"/"dado sensível" são exercitados por teste
  injetando um resultado bloqueado — a CLI/chat os renderiza com segurança,
  mas não há flag de usuário que os force.
- Agora existem **duas** superfícies dry-run (CLI e chat) com lógicas
  paralelas (`cli_dry_run.py` e `chat_dry_run.py`). Elas compartilham o mesmo
  contrato mas não o mesmo código; uma futura unificação (helper comum) poderia
  reduzir duplicação — fora do escopo desta fase, registrado para MC19+.
- O `handle_chat_dry_run` roteia por `toks[1] == "simular"`. Um futuro alias
  precisará ser adicionado explicitamente; hoje só `simular` roda dry-run.

## 12. Próximo passo recomendado

MC19 — Documentation/Public UX Alignment for CLI+Chat Dry-run: alinhar README,
UX spec e textos de ajuda (`/ajuda`, `nomos --help`) agora que as **duas**
superfícies dry-run (`nomos conselho simular` e `/conselho simular`) existem,
deixando claro o que é dry-run e o que segue desabilitado.
