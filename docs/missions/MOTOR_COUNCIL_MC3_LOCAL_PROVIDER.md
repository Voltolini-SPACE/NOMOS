# MOTOR COUNCIL MC3 — LOCAL CANDIDATE PROVIDER CONTRACT

## 1. Status final

STATUS_FINAL=PASS_MOTOR_COUNCIL_MC3_LOCAL_PROVIDER_CONTRACT

Contrato de provedor de candidatos locais criado, com provider determinístico de
teste. 31 testes novos. Sem motor real, Ollama, cloud, rede, persistência, ou
policy/audit/vault reais. Juízes/árbitro/gate seguem simulados.

## 2. Baseline

| Item | Resultado |
|---|---|
| BASELINE_HEAD | e483f80 |
| BASELINE_TAG | v1.2.0rc3-audit-anchored-11-ge483f80 |
| GIT_STATUS | CLEAN (antes dos commits) |
| GIT_FSCK | PASS |
| RUFF | PASS |
| PYTEST | PASS_606 → PASS_608 |
| BUILD | PASS (wheel inclui `council/local_provider.py`) |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | PASS (LEGACY_UNANCHORED esperado) |

## 3. Escopo

```text
LOCAL_PROVIDER_CONTRACT=true
REAL_ENGINE_EXECUTION=false
CLOUD=false
NETWORK=false
PERSISTENCE=false
JUDGES_REAL=false
ARBITER_REAL=false
POLICY_GATE_REAL=false
AUDIT_REAL=false
```

## 4. O que foi criado

| Símbolo | Papel |
|---|---|
| `LocalEngineDescriptor` | descreve um motor; `engine_id` exige `local:`; `is_local_safe`/`can_handle()` |
| `LocalProviderFailure` | falha mapeada a `CouncilFailureCode` |
| `LocalCandidateRequest` | pedido (prompt não vaza em repr/to_dict); `cloud_allowed=False`; `local_only=True` |
| `LocalCandidateResult` | candidatos + failure_code + warnings; repr sem prompt/conteúdo |
| `LocalCandidateProvider` | `Protocol` (list_engines / generate) |
| `DeterministicLocalCandidateProvider` | provider FAKE determinístico (sem motor/rede/FS/env/time/random) |
| `run_offline_council_with_local_provider(...)` | integração: candidatos locais + pipeline MC2 |

Consolidação: o `local_engine.py` da iteração MC3 anterior foi **superseded** por
este `local_provider.py` (contrato com códigos de falha distintos) e removido,
junto de seus testes, para não haver dois provedores paralelos.

## 5. Contrato LocalCandidateProvider

Um `LocalEngineDescriptor` é **local-safe** só se `engine_id` começa por
`local:`, `local_only=True`, `cloud=False` e `network_required=False`.
`can_handle(sensível)` exige, além disso, `supports_sensitive_data=True` quando o
dado é sensível. `generate()` escolhe o `CouncilFailureCode` por causa:

| Situação | failure_code |
|---|---|
| nenhum motor / nenhum local | `NO_ELIGIBLE_LOCAL_ENGINE` |
| motor declara cloud/rede | `CLOUD_BLOCKED_BY_LOCAL_LOCK` |
| dado sensível, nenhum motor capaz | `SENSITIVE_DATA_CLOUD_DENIED` |
| sucesso | `None` (candidatos locais) |

O provider nunca chama rede/cloud/FS/env, nunca usa tempo/random, e nunca embute
o prompt no conteúdo (resposta fixa determinística por motor).

## 6. Integração com simulador

`run_offline_council_with_local_provider(request, provider, judge_fixtures, gate)`:

```text
LocalCandidateRequest → provider.generate() → AnswerCandidate[] (locais)
  → OfflineCouncilSimulator.run_with_candidates(judges=fixtures, gate=simulado)
  → reviews/árbitro/gate SIMULADOS → OfflineCouncilResult
```

`run()` do MC2 continua idêntico. Se o provider falha, o `failure_code` é
propagado e a decisão do árbitro fica bloqueada.

## 7. Regras de segurança implementadas

- Motor exige prefixo `local:`; cloud/rede/não-local ⇒ inelegível (nunca usado).
- Provider/integração: **sem rede, cloud, SDK remoto (OpenAI/Anthropic/Gemini/
  Ollama), subprocess/threading/asyncio, FS, env, tempo real, random**.
- Sem policy/vault/audit reais; só importa `nomos.council.models` e `.simulator`.
- Fail-closed por causa (tabela acima); dado sensível exige motor capaz.
- Invariantes MC1/MC2 preservadas: paranoid → local-only; sensível → cloud
  negada; privado → sem persistência.
- Determinístico: mesma entrada ⇒ mesma saída (byte a byte no JSON).
- Prompt nunca em `repr`, `to_dict`, `LocalCandidateResult` nem no resultado.

## 8. Testes adicionados

| Arquivo | Testes |
|---|---|
| tests/test_council_local_provider.py | 23 (descriptor/request/provider/integração/determinismo) |
| tests/test_council_local_provider_security.py | 8 (sem rede/subprocess/asyncio/SDK cloud/motor; sem FS/env; sem time/random; sem policy/vault/audit) |

Total novo: **31** (mínimo exigido: 24). Suíte completa: **608**. Todos os 27
nomes obrigatórios da missão estão presentes.

## 9. Não escopo (confirmado)

Sem motor real · sem Ollama · sem roteador real · sem juiz real · sem árbitro
real com LLM · sem CLI · sem chat commands · sem persistência · sem cloud · sem
rede · sem policy/audit/vault reais · sem PyPI/release/tag.

## 10. Riscos remanescentes

- O provider concreto é um **fake determinístico**; um adaptador para motor local
  real (ex.: llama.cpp embutido) entra na MC4 e precisará provar, por teste, que
  não abre rede.
- O gate ainda é **simulado**; a integração com o `policy.gate` A0–A6 real entra
  numa fase posterior.
- Auditoria/redação reais e persistência controlada entram depois (MC5+).

## 11. Próximo passo recomendado

Iniciar a **Fase MC4 — Local Engine Adapter SPEC/DRY-RUN** sob
`implementation-loop-100`: especificar e simular (dry-run) um adaptador de motor
local real, **ainda sem chamar o motor por padrão**, provando o isolamento de
rede antes de qualquer execução real.
