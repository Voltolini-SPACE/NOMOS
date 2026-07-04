# MOTOR COUNCIL MC3 — LOCAL ENGINE INTEGRATION

## 1. Status final

STATUS_FINAL=PASS_MOTOR_COUNCIL_MC3_LOCAL_ENGINE_INTEGRATION

Camada de geração de candidatos por motores LOCAIS criada por contrato. 29
testes novos. Sem cloud, sem rede, sem SDK remoto, sem persistência, sem
policy/audit/vault reais, sem CLI/chat. Juízes/árbitro/gate seguem simulados.

## 2. Baseline

| Item | Resultado |
|---|---|
| BASELINE_HEAD | c91ae25 |
| BASELINE_TAG | v1.2.0rc3-audit-anchored-8-gc91ae25 |
| GIT_STATUS | CLEAN (antes dos commits) |
| GIT_FSCK | PASS |
| RUFF | PASS |
| PYTEST | PASS_577 → PASS_606 |
| BUILD | PASS (wheel inclui `council/local_engine.py`) |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | PASS (LEGACY_UNANCHORED esperado) |

## 3. Escopo

```text
LOCAL_ENGINE_INTEGRATION=true
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
| `LocalEngineDescriptor` | descreve um motor; `engine_id` exige prefixo `local:`; `is_eligible`/`eligibility()` |
| `LocalEngineEligibility` | (eligible, reason) |
| `LocalEngineFailure` | falha mapeada a `CouncilFailureCode` |
| `LocalCandidateRequest` | pedido (prompt não vaza no repr); `cloud_allowed=False` sempre; `local_only=True` |
| `LocalCandidateResult` | candidatos + failure_code + warnings (sem prompt) |
| `LocalCandidateProvider` | `Protocol` (list_engines / generate) |
| `DeterministicLocalCandidateProvider` | provider FAKE determinístico p/ testes |
| `run_offline_council_with_local_candidates(...)` | integração: candidatos locais + pipeline MC2 |

Refactor de apoio: `OfflineCouncilSimulator.run_with_candidates(...)` (reutilizável;
`run()` delega, MC2 idêntico).

## 5. Contrato local engine

Um `LocalEngineDescriptor` só é **elegível** se `engine_id` começa por `local:`,
`local_only=True`, `cloud=False` e `network_required=False`. Um motor que declare
cloud ou rede é representável, porém **inelegível** — o provider o ignora (com
warning) e, se não sobrar motor elegível, falha fechado
(`NO_ELIGIBLE_LOCAL_ENGINE`). O provider nunca chama rede/cloud/FS/env e nunca
guarda o prompt (o conteúdo do candidato é resposta fixa determinística, jamais o
prompt do usuário).

## 6. Integração com o simulador

`run_offline_council_with_local_candidates(request, provider, judge_fixtures,
gate)`:

```text
LocalCandidateRequest → provider.generate() → AnswerCandidate[] (locais)
  → OfflineCouncilSimulator.run_with_candidates(judges=fixtures, gate=simulado)
  → reviews/árbitro/gate SIMULADOS → OfflineCouncilResult
```

Só a **origem dos candidatos** mudou (fixture → motor local); juízes, árbitro e
gate continuam simulados (MC2). Se o provider falha, o `failure_code` é
propagado e a decisão do árbitro fica bloqueada.

## 7. Regras de segurança implementadas

- Motor exige prefixo `local:`; cloud/rede/não-local ⇒ inelegível (nunca usado).
- Provider e integração: **sem rede, sem cloud, sem SDK remoto (OpenAI/Anthropic/
  Ollama), sem subprocess/threading/asyncio, sem FS, sem env**.
- Sem policy/vault/audit reais; o módulo só importa `nomos.council.models` e
  `nomos.council.simulator`.
- Fail-closed: sem motor elegível ⇒ `NO_ELIGIBLE_LOCAL_ENGINE`; gate negado ⇒
  bloqueado.
- Invariantes MC1/MC2 preservadas: paranoid → local-only; sensível → cloud
  negada; privado → sem persistência.
- Determinístico: mesma entrada ⇒ mesma saída (byte a byte no JSON).
- Prompt nunca aparece em `repr`, no `LocalCandidateResult` nem no resultado.

## 8. Testes adicionados

| Arquivo | Testes |
|---|---|
| tests/test_council_local_engine.py | 21 (descriptor/request/provider/integração) |
| tests/test_council_local_engine_security.py | 8 (sem rede/subprocess/asyncio/SDK cloud; sem FS; sem env; sem policy/vault/audit; determinismo) |

Total novo: **29** (mínimo exigido: 20). Suíte completa: **606**. Todos os 22
nomes obrigatórios da missão estão presentes.

Correção real durante o desenvolvimento: `DeterministicLocalCandidateProvider([])`
caía no default (lista vazia é falsy); ajustado para distinguir `None` (usa
mock) de `[]` (sem motor), garantindo o fail-closed. Coberto por teste.

## 9. Não escopo (confirmado)

Sem cloud · sem rede · sem LLM real obrigatório · sem juiz real · sem árbitro
real · sem CLI · sem chat commands · sem persistência · sem policy/audit/vault
reais · sem alterar router/agents/skills/motores · sem PyPI/release/tag.

## 10. Riscos remanescentes

- O provider concreto ainda é um **fake determinístico**; um provider ligado a um
  motor local real (ex.: llama.cpp embutido) entra numa fase posterior e precisa
  provar, também por teste, que não abre rede.
- O gate aqui é **simulado**; a integração com o `policy.gate` real e o
  fail-closed sem aprovador entram na **MC4**.
- Auditoria/redação reais e persistência controlada (modo privado no disco)
  entram na **MC5**.

## 11. Próximo passo recomendado

Iniciar a **Fase MC4 (policy gate integration)** sob `implementation-loop-100`:
substituir o `SimulatedPolicyGateResult` pelo `policy.gate` A0–A6 real antes da
resposta final (fail-closed sem aprovador), mantendo candidatos locais e
juízes/árbitro ainda simulados.
