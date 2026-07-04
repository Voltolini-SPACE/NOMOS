# MOTOR COUNCIL MC8 — ORCHESTRATOR SPEC/DRY-RUN

## 1. Status final

STATUS_FINAL=PASS_MOTOR_COUNCIL_MC8_ORCHESTRATOR_DRY_RUN

Orquestrador dry-run criado, compondo provider local → simulador → policy gate
→ audit envelope num único fluxo em memória. 54 testes novos provam a ordem
determinística do trace, o comportamento fail-closed de ponta a ponta (A6,
dado sensível, sem candidatos, exceção de componente plugável) e a propagação
de `private_mode` para todos os envelopes. Nenhum motor real, Ollama,
subprocess, HTTP, cloud, policy/vault/audit/approval real, CLI ou chat command
foi criado ou chamado. Nenhuma tag ou release foi criada.

## 2. Baseline

| Item | Resultado |
|---|---|
| BASELINE_HEAD | 34e4338 |
| BASELINE_TAG | v1.2.0rc3-audit-anchored-26-g34e4338 |
| GIT_STATUS | CLEAN (antes das mudanças) |
| GIT_FSCK | PASS (1 commit dangling pré-existente, benigno) |
| RUFF | PASS |
| PYTEST | PASS_724 |
| BUILD | PASS_IN_TMP_SANDBOX_FS_QUIRK |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | WARN (LOG_LEGACY_UNANCHORED, esperado) |

`python -m build` no diretório montado do sandbox estoura `RecursionError` na
limpeza de tempdir do backend (quirk de FS fuse, não do pacote); o wheel
compila normalmente em `/tmp` e o job `smoke` do CI builda nos 3 SOs sem esse
quirk. O mesmo quirk de FS bloqueou `rm`/`os.remove` num `.git/index.lock`
remanescente (inclusive via `pytest --cov` tentando `coverage.erase()`) — ambos
resolvidos rodando a operação em `/tmp` (build/cobertura) ou diretamente no
Mac real via Desktop Commander (lock do git), sem mascarar nada.

## 3. Escopo

```text
ORCHESTRATOR_DRY_RUN=true
REAL_ENGINE_EXECUTION=false
REAL_POLICY=false
REAL_AUDIT=false
REAL_VAULT=false
CLOUD=false
NETWORK=false
SUBPROCESS=false
PERSISTENCE=false
```

## 4. O que foi criado

| Símbolo | Papel |
|---|---|
| `CouncilOrchestrationInput` | entrada (session_id, prompt, mode, risk_level, private_mode, contains_sensitive_data, max_candidates); prompt nunca em `to_dict`/`repr` (só `prompt_chars`) |
| `CouncilOrchestrationStepName` | 9 eventos de etapa (INPUT_VALIDATED … ORCHESTRATION_BLOCKED) |
| `CouncilOrchestrationStep` | etapa do trace; metadata-only; rejeita chave/valor sensível na construção |
| `CouncilOrchestrationTrace` | lista ordenada de etapas; `dry_run=true`/`redacted=true` sempre |
| `OrchestrationFailureCode` | 9 códigos `ORCH_*` |
| `CouncilOrchestrationFailure` | par (código, motivo) interno |
| `CouncilOrchestrationResult` | resultado composto; `dry_run`/`would_execute=false`/`would_write_audit=false` sempre; `final_envelope`/`audit_result`/`trace` já serializados |
| `CouncilOrchestratorDryRun` | orquestrador — `.run(entrada) -> CouncilOrchestrationResult` |
| `OrchestratorError` | erro de configuração (fail-closed) |

## 5. Fluxo orquestrado

`CouncilOrchestratorDryRun` compõe, por padrão, `DryRunAdapterCandidateProvider`
(MC4, sobre `DryRunLocalEngineAdapter`) → `OfflineCouncilSimulator` (MC2,
`run_with_candidates`, com juízes fixos determinísticos — um por candidato,
nota máxima, nunca um "judge real com LLM") → `CouncilPolicyGateDryRun` (MC6,
avaliado diretamente para produzir uma etapa própria) → `FinalResponseEnvelope`
(MC6) → `CouncilAuditEnvelopeBuilder.build_for_result` (MC7). Provider,
simulador, gate e audit builder são injetáveis no construtor (para testes e
composição futura), todos com default dry-run.

## 6. Ordem obrigatória

O trace sempre contém, nesta ordem, quando a entrada é válida:

```text
INPUT_VALIDATED → LOCAL_PROVIDER_EVALUATED → CANDIDATES_CREATED →
SIMULATOR_RAN → POLICY_GATE_EVALUATED → FINAL_ENVELOPE_CREATED →
AUDIT_ENVELOPE_CREATED → ORCHESTRATION_COMPLETED | ORCHESTRATION_BLOCKED
```

Isso vale tanto no caminho feliz quanto em **qualquer** bloqueio downstream
(gate negado, dado sensível, sem candidatos, exceção de gate/audit builder) —
o pipeline nunca pula etapas por causa de uma falha; ele continua registrando
o trace completo e usa a **causa-raiz** (a primeira etapa que falhou) como
`failure_code` do resultado. A única exceção é entrada estruturalmente
inválida (`ORCH_INPUT_INVALID`, ex.: `session_id` mutado para vazio após a
construção): aí o pipeline pára logo após `INPUT_VALIDATED`, pois nenhuma
etapa downstream pode confiar num identificador de sessão inválido —
comportamento provado por
`test_orchestrator_input_invalid_after_tampering_fails_closed`.
`POLICY_GATE_EVALUATED` é sempre anterior a `FINAL_ENVELOPE_CREATED`, e este
sempre anterior a `AUDIT_ENVELOPE_CREATED` (provado por teste em múltiplos
cenários, inclusive bloqueados).

## 7. Fail-closed behavior

| Situação | failure_code | Observação |
|---|---|---|
| risk_level=A6 | `ORCH_POLICY_GATE_DENIED` | gate nega via `GATE_A6_DENIED`; `final_envelope.content=null` |
| contains_sensitive_data=true | `ORCH_POLICY_GATE_DENIED` | gate nega via `GATE_SENSITIVE_DATA_REQUIRES_STRICT_MODE`; nunca cloud (contrato do provider local) |
| provider sem motor elegível | `ORCH_NO_CANDIDATES` | ex.: `DeterministicLocalCandidateProvider(engines=[])` |
| provider retorna motor cloud/rede | `ORCH_PROVIDER_FAILED` | `CLOUD_BLOCKED_BY_LOCAL_LOCK` mapeado |
| provider/gate/audit builder lançam exceção | `ORCH_PROVIDER_FAILED` / `ORCH_INTERNAL_INVARIANT_FAILED` | nunca propaga; capturado e convertido em bloqueio |
| simulador lança exceção (defesa; inalcançável via pipeline puro) | `ORCH_SIMULATOR_FAILED` | testado injetando um simulador fake |
| audit builder nega (metadata sensível, etc.) | `ORCH_AUDIT_ENVELOPE_DENIED` | testado injetando um builder fake |
| entrada inválida pós-construção | `ORCH_INPUT_INVALID` | defesa em profundidade; pipeline pára cedo |
| invariante de modo privado violada (defesa; inalcançável pelos modelos reais) | `ORCH_PRIVATE_MODE_PERSIST_DENIED` | testado via `_verificar_persist_privado` direto |
| invariante dry-run violada (defesa; inalcançável pelos modelos reais) | `ORCH_DRY_RUN_ONLY` | testado via `_verificar_dry_run_only` direto |

## 8. Private mode

`private_mode=true` no `CouncilOrchestrationInput` propaga para: (a) o
`FinalResponseEnvelope` (`persist_allowed=false`); (b) todos os envelopes do
`CouncilAuditEnvelopeBuilder` (`persist_allowed=false` em cada um); (c) o
`CouncilOrchestrationTrace` (`private_mode=true`, `redacted=true`). Uma
checagem de defesa em profundidade (`_verificar_persist_privado`) confirma,
após montar o envelope final e o resultado de auditoria, que nenhum dos dois
declara `persist_allowed=true` sob modo privado — na prática inalcançável
porque os modelos reais (MC6/MC7) já forçam isso por construção, mas exercida
diretamente por teste com objetos fabricados.

## 9. Segurança implementada

- Módulo **não importa** o harness de execução real (`local_harness`) — nem a
  constante `REAL_LOCAL_ENGINE_EXECUTION_ENABLED`, nem `LocalExecutionHarness`,
  nem `.execute(` aparecem no código-fonte. Não há caminho, direto ou
  indireto, para execução real através deste módulo.
- Não importa rede (`socket`/`http`/`urllib`/`requests`/`httpx`/…),
  `subprocess`/`threading`/`multiprocessing`/`asyncio`, SDKs cloud
  (`openai`/`anthropic`/`google.generativeai`/…) nem motores reais
  (`ollama`/`llama_cpp`/`transformers`/`torch`/`nomos.runtime`/…).
- Não toca filesystem (`pathlib`/`os`/`io`/…), não usa `os.environ`/`getenv`,
  não usa `time`/`datetime.now`/`random`/`secrets`.
- Só importa stdlib (`json`, `dataclasses`, `enum`, `__future__`) e seis
  submódulos já dry-run do próprio `nomos.council` (models, local_provider,
  local_adapter, simulator, policy_gate, audit_envelope) — nunca
  `nomos.kernel.policy/vault/audit/...`, nunca `nomos.agents`/`nomos.skills`/
  `nomos.router`. Nenhuma menção a `nomos conselho` ou `/conselho`.
- Determinístico: mesma entrada ⇒ mesmo resultado (provado por teste).
- Prompt nunca aparece em `to_dict`/`to_json`/`repr` do input, do trace ou do
  resultado (só `prompt_chars`); conteúdo de candidato/final nunca aparece no
  trace; `engine_id` nunca aparece em nenhuma etapa do trace (privado ou não).

## 10. Testes adicionados

| Arquivo | Testes |
|---|---|
| tests/council/test_orchestrator.py | 43 (contratos, comportamentos obrigatórios, ordem do trace, robustez/exceções, invariantes diretas) |
| tests/council/test_orchestrator_security.py | 11 (segurança AST: rede, subprocess/threading/asyncio, cloud, motores reais, FS/env, tempo/random, policy/vault/audit/approval, harness real, adaptador dry-run, só stdlib+council, sem agentes/skills/router) |

Total novo: **54** (mínimo exigido: 34). Suíte completa: **778** (era 724).
Todos os 34 nomes de teste exigidos pela missão estão presentes (conferido por
diff de nomes antes da entrega).

## 11. Não escopo

Confirmado:
- sem motor real, sem Ollama, sem llama.cpp
- sem subprocess, sem HTTP local/externo, sem cloud (OpenAI/Anthropic/Gemini)
- sem roteador real, sem judge real com LLM, sem arbiter real com LLM
- sem CLI `nomos conselho`, sem chat command `/conselho`
- sem persistência em disco, sem agentes/skills usando o Council
- sem threads/timers/background jobs, sem alteração do roteador global
- sem bypass de gate, sem bypass de private mode
- sem policy/audit/vault/approval reais chamados
- nenhuma tag criada, nenhum release criado

## 12. Riscos remanescentes

- O orquestrador ainda não é chamado por nenhum CLI/chat real (correto para
  esta fase) — a próxima integração real deverá reusar exatamente este
  `CouncilOrchestratorDryRun.run()` como ponto único de composição.
- `ORCH_SIMULATOR_FAILED` é, por desenho, inalcançável através do pipeline
  padrão (o `OfflineCouncilSimulator` é puro e nunca lança para entradas bem
  formadas construídas pelo próprio orquestrador); está testado via injeção de
  um simulador fake, não via uso normal.
- O `session_id` visível nos envelopes de auditoria (MC7) permanece o
  identificador interno fixo do simulador (`offline-sim`), não o
  `session_id` fornecido pelo chamador ao orquestrador — o `CouncilGateRequest`
  e o `FinalResponseEnvelope` já usam o `session_id` do chamador, mas
  `CouncilAuditEnvelopeBuilder.build_for_result` deriva o dele do resultado do
  simulador. É uma inconsistência cosmética herdada do contrato do MC7 (fora
  do escopo desta missão alterar `audit_envelope.py`), não um problema de
  segurança — nenhum conteúdo vaza de qualquer forma.
- O provider padrão (`DryRunAdapterCandidateProvider`/MC4) não verifica
  `supports_sensitive_data` por motor (essa checagem só existe no
  `DeterministicLocalCandidateProvider`/MC3) — na prática isso não abre brecha
  porque o Policy Gate (MC6) bloqueia dado sensível de qualquer forma antes de
  liberar conteúdo, mas vale registrar para uma eventual unificação dos dois
  providers numa fase futura.

## 13. Próximo passo recomendado

Fase MC9 — CLI/Chat UX SPEC-only para desenhar os comandos futuros `nomos
conselho` e `/conselho` (sem implementar comandos reais ainda).
