# MOTOR COUNCIL MC5 — LOCAL ADAPTER HARNESS FAIL-CLOSED

## 1. Status final

STATUS_FINAL=PASS_MOTOR_COUNCIL_MC5_LOCAL_HARNESS_FAIL_CLOSED

Harness de execução local criado com a trava literal
`REAL_LOCAL_ENGINE_EXECUTION_ENABLED = False`. Toda tentativa de execução real é
bloqueada por construção (`executed=false`, `candidate=null`). 26 testes novos.
Sem motor, Ollama, subprocess, HTTP, cloud, SDK remoto, FS, env, tempo ou random.

## 2. Baseline

| Item | Resultado |
|---|---|
| BASELINE_HEAD | 09b0bf4 |
| BASELINE_TAG | v1.2.0rc3-audit-anchored-17-g09b0bf4 |
| GIT_STATUS | CLEAN (antes dos commits) |
| GIT_FSCK | PASS |
| RUFF | PASS |
| PYTEST | PASS_637 → PASS_663 |
| BUILD | PASS_IN_TMP_SANDBOX_FS_QUIRK (wheel `nomos-1.3.0rc13` em `/tmp`, inclui `local_harness.py`) |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | PASS (LEGACY_UNANCHORED esperado) |

`python -m build` no diretório montado estoura `RecursionError` na limpeza de
tempdir do backend (quirk do FS fuse do sandbox). O pacote compila em `/tmp` e o
job `smoke` do CI builda nos 3 SOs.

## 3. Escopo

```text
LOCAL_HARNESS=true
REAL_EXECUTION_ENABLED=false
REAL_ENGINE_EXECUTION=false
CLOUD=false
NETWORK=false
SUBPROCESS=false
PERSISTENCE=false
JUDGES_REAL=false
ARBITER_REAL=false
POLICY_GATE_REAL=false
AUDIT_REAL=false
```

## 4. O que foi criado

| Símbolo | Papel |
|---|---|
| `REAL_LOCAL_ENGINE_EXECUTION_ENABLED` | constante literal `False` (a trava) |
| `LocalExecutionRequest` | pedido; `engine_id` `local:`; guarda só `prompt_chars` |
| `LocalExecutionAttemptRecord` | tentativa: `would_execute=true` conceitual, `executed=false`, `blocked=true` |
| `LocalExecutionResult` | `allowed=false`, `executed=false`, `candidate=null` sempre |
| `LocalExecutionFailure` / `ExecutionFailureCode` | REAL_EXECUTION_DISABLED e afins |
| `LocalExecutionHarness` | `execute()` sempre fail-closed |
| `real_execution_enabled()` | getter read-only da trava (não há setter) |

## 5. Flag hardcoded

```python
REAL_LOCAL_ENGINE_EXECUTION_ENABLED = False
```

Literal `False`, no topo do módulo. Não vem de env, config ou argumento; o módulo
não lê variáveis do sistema. Não existe função pública que a ligue (nada de
enable/activate/unlock/set_enabled) — provado por teste (AST + `dir()`), que
também garante que a constante é atribuída **uma única vez**. Remover a trava
exige uma edição explícita e auditável deste arquivo.

## 6. Harness

`LocalExecutionHarness.execute(request)` verifica a trava e devolve sempre um
`LocalExecutionResult` bloqueado: nunca chama motor/subprocess/rede/FS/env/
policy/vault/audit, sem tempo/random. Motor não-local é barrado antes mesmo da
trava (`REAL_EXECUTION_ENGINE_NOT_LOCAL`); o caminho principal (motor local) cai
em `REAL_EXECUTION_DISABLED`. O ramo "habilitado" é inalcançável (flag `False`).

## 7. Fail-closed behavior

| Cenário | Saída |
|---|---|
| motor local (`local:mock-a`) | allowed=false, executed=false, `REAL_EXECUTION_DISABLED`, candidate=null |
| motor não-local (`remote:model`) | executed=false, `REAL_EXECUTION_ENGINE_NOT_LOCAL`, candidate=null |
| `private_mode=true` | `attempt.persist_allowed=false`, executed=false |
| env `...ENABLED=1` setado | executed=false, `REAL_EXECUTION_DISABLED` (env ignorado) |
| dry-run do MC4 | intacto: allowed=true, dry_run=true, would_execute=false |

## 8. Regras de segurança implementadas

- `executed=false` e `candidate=null` SEMPRE; `allowed=false` para execução real.
- Trava literal, sem API de ativação, sem env/config/argumento.
- Módulo **não importa** rede/cloud/SDK/motor/subprocess/threading/asyncio;
  **não toca** FS; **não usa** env/`time`/`datetime.now`/`random`.
- Sem policy/vault/audit reais; só importa `nomos.council.models`.
- Determinístico e sem mutação da flag global (provado por teste).
- Prompt nunca é armazenado (só `prompt_chars`) nem vaza em repr/serialização.

## 9. Testes adicionados

| Arquivo | Testes |
|---|---|
| tests/test_council_local_harness.py | 17 (flag literal, request, fail-closed, private, env, roundtrip, determinismo, dry-run intacto) |
| tests/test_council_local_harness_security.py | 9 (sem rede/subprocess/asyncio/SDK/motor/FS/env/time/random; sem policy/vault/audit; sem API de ativação) |

Total novo: **26** (mínimo exigido: 24). Suíte completa: **663**. Todos os 24
nomes obrigatórios da missão estão presentes.

## 10. Não escopo (confirmado)

Sem motor real · sem Ollama · sem subprocess · sem HTTP · sem roteador real · sem
juiz real · sem árbitro real com LLM · sem CLI · sem chat commands · sem
persistência · sem cloud · sem rede · sem policy/audit/vault reais ·
sem PyPI/release/tag.

## 11. Riscos remanescentes

- O caminho de execução real é apenas **representado**; ligá-lo exigiria editar a
  constante literal — nenhuma via dinâmica existe. Uma fase futura de execução
  controlada precisaria de aprovação humana explícita e gate real antes de mudar
  a flag.
- O gate segue **simulado**; a integração com o `policy.gate` A0–A6 real vem na
  próxima fase (MC6).

## 12. Próximo passo recomendado

Iniciar a **Fase MC6 — Policy Gate Integration SPEC/DRY-RUN** sob
`implementation-loop-100`, ainda sem execução real, para provar que **toda
resposta final simulada passa pelo gate** (A0–A6) antes de sair, com fail-closed
sem aprovador.
