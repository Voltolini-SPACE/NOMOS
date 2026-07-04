# MOTOR COUNCIL MC4 — LOCAL ENGINE ADAPTER SPEC/DRY-RUN

## 1. Status final

STATUS_FINAL=PASS_MOTOR_COUNCIL_MC4_LOCAL_ADAPTER_DRY_RUN

Adaptador de motor local em SPEC/DRY-RUN criado. **Nenhuma execução real**:
`would_execute=false` e `dry_run=true` sempre. 29 testes novos. Sem motor,
Ollama, subprocess, HTTP, cloud, SDK remoto, FS, env, tempo ou random.

## 2. Baseline

| Item | Resultado |
|---|---|
| BASELINE_HEAD | 10ad92b |
| BASELINE_TAG | v1.2.0rc3-audit-anchored-14-g10ad92b |
| GIT_STATUS | CLEAN (antes dos commits) |
| GIT_FSCK | PASS |
| RUFF | PASS |
| PYTEST | PASS_608 → PASS_637 |
| BUILD | PASS (wheel `nomos-1.3.0rc12`, inclui `council/local_adapter.py`) * |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | PASS (LEGACY_UNANCHORED esperado) |

\* O pacote compila (provado com wheel em `/tmp`). No diretório montado do
sandbox, `python -m build` estoura `RecursionError` na limpeza de tempdir do
backend (quirk do FS fuse, não do pacote); os runners limpos do CI buildam
normalmente (job `smoke` nos 3 SOs).

## 3. Escopo

```text
LOCAL_ADAPTER_DRY_RUN=true
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
| `LocalEngineIsolationProfile` | nega tudo por padrão; qualquer permissão ⇒ erro |
| `LocalEngineAdapterPolicy` | `dry_run_only`/`local_only` obrigatórios; allow_* proibidos; limites > 0 |
| `LocalEngineExecutionPlan` | plano dry-run (`would_execute=false`, `dry_run=true`); sem prompt |
| `LocalEngineDryRunResult` | resultado do ensaio; candidato simulado ou None; sem prompt |
| `LocalEngineAdapter` | `Protocol` (plan / dry_run) |
| `DryRunLocalEngineAdapter` | adaptador dry-run puro (determinístico) |
| `DryRunAdapterCandidateProvider` | provider (contrato MC3) via adaptador dry-run |
| `AdapterFailureCode` / `LocalAdapterFailure` | códigos ADAPTER_* + mapeamento a `CouncilFailureCode` |

## 5. Execution plan

`LocalEngineExecutionPlan` representa a chamada FUTURA sem executá-la:
`would_execute=false` e `dry_run=true` são forçados na construção (mesmo que se
passe `would_execute=True`). `adapter_id` exige prefixo `dryrun:`; um plano
não-bloqueado exige `engine_id` `local:`. Guarda apenas `prompt_chars` (tamanho),
nunca o prompt; `repr`/`to_dict` não vazam o prompt.

## 6. Isolation profile

`LocalEngineIsolationProfile` nega por padrão network/subprocess/filesystem/env/
cloud/loopback. Qualquer campo `True` ⇒ `AdapterError` (proibido nesta fase).

## 7. Adapter policy

`LocalEngineAdapterPolicy` exige `dry_run_only=True` e `local_only=True`; qualquer
`allow_*` verdadeiro ⇒ `AdapterError`; `max_prompt_chars`/`max_output_chars`
devem ser inteiros > 0. Prompt acima do limite ⇒ `ADAPTER_PROMPT_TOO_LARGE`.

## 8. Provider com adapter

`DryRunAdapterCandidateProvider` usa o `DryRunLocalEngineAdapter` para cada motor,
coleta candidatos simulados (id `dry_cand_*`), respeita `max_candidates`, e falha
fechado quando o adaptador bloqueia (mapeando `AdapterFailureCode` →
`CouncilFailureCode`). Integra com `run_offline_council_with_local_provider` do
MC3 sem alterar o provider determinístico anterior.

Mapeamento de falhas:

| AdapterFailureCode | CouncilFailureCode |
|---|---|
| ADAPTER_ENGINE_NOT_LOCAL / ADAPTER_ENGINE_INELIGIBLE | NO_ELIGIBLE_LOCAL_ENGINE |
| ADAPTER_CLOUD_DENIED / ADAPTER_NETWORK_DENIED / *_DENIED (subprocess/fs/env/loopback) | CLOUD_BLOCKED_BY_LOCAL_LOCK |
| ADAPTER_PROMPT_TOO_LARGE | ENGINE_FAILED |

## 9. Regras de segurança implementadas

- `would_execute=false` sempre; nada é executado.
- Isolation nega tudo; policy nega cloud/network/subprocess/filesystem/env/loopback.
- Módulo **não importa** rede/cloud/SDK remoto/motor real/subprocess/threading/
  asyncio; **não toca** FS; **não usa** env/`time`/`datetime.now`/`random`.
- Sem policy/vault/audit reais; só importa `nomos.council.models` e
  `nomos.council.local_provider`.
- Determinístico e sem mutação de estado global (provado por teste).
- Prompt nunca no plano, resultado, warnings, conteúdo ou repr.

## 10. Testes adicionados

| Arquivo | Testes |
|---|---|
| tests/test_council_local_adapter.py | 20 (isolation/policy/plan/dry-run/provider/integração) |
| tests/test_council_local_adapter_security.py | 9 (sem rede/subprocess/asyncio/SDK/motor/FS/env/time/random; sem policy/vault/audit; sem mutação global) |

Total novo: **29** (mínimo exigido: 28). Suíte completa: **637**. Todos os 28
nomes obrigatórios da missão estão presentes.

## 11. Não escopo (confirmado)

Sem motor real · sem Ollama · sem subprocess · sem HTTP · sem roteador real · sem
juiz real · sem árbitro real com LLM · sem CLI · sem chat commands · sem
persistência · sem cloud · sem rede · sem policy/audit/vault reais · sem
PyPI/release/tag.

## 12. Riscos remanescentes

- O adaptador é **dry-run**; a execução real só existiria numa fase futura, e a
  MC5 deve mantê-la **bloqueada por flag hardcoded false**, provando que o
  caminho real permanece fail-closed antes de qualquer chamada de motor.
- O gate segue **simulado**; a integração com o `policy.gate` A0–A6 real vem
  depois.
- Auditoria/redação/persistência reais entram em fases posteriores.

## 13. Próximo passo recomendado

Iniciar a **Fase MC5 — Local Adapter Harness** sob `implementation-loop-100`,
com **execução real ainda bloqueada por flag hardcoded `False`**, provando por
teste que o caminho de execução real permanece fail-closed e que remover o
bloqueio exigiria uma mudança explícita e auditável.
