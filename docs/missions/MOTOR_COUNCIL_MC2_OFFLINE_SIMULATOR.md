# MOTOR COUNCIL MC2 — OFFLINE SIMULATOR

## 1. Status final

STATUS_FINAL=PASS_MOTOR_COUNCIL_MC2_OFFLINE_SIMULATOR

Simulador offline determinístico criado sobre os modelos puros do MC1. 26 testes
novos. Nenhum motor real, LLM, rede, persistência, CLI, chat ou integração com
policy/audit/vault reais.

## 2. Baseline

| Item | Resultado |
|---|---|
| BASELINE_HEAD | b8812d9 |
| BASELINE_TAG | v1.2.0rc3-audit-anchored-5-gb8812d9 |
| GIT_STATUS | CLEAN (antes dos commits) |
| GIT_FSCK | PASS |
| RUFF | PASS |
| PYTEST | PASS_551 → PASS_577 |
| BUILD | PASS (wheel inclui `council/simulator.py`) |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | PASS (LEGACY_UNANCHORED esperado) |

## 3. Escopo

```text
OFFLINE_SIMULATOR=true
ENGINE_EXECUTION=false
PERSISTENCE=false
CLI=false
CHAT_COMMANDS=false
NETWORK=false
```

## 4. O que foi criado

| Símbolo | Papel |
|---|---|
| `SimulatedEngineFixture` | resposta já pronta (não motor); `engine_id` exige prefixo `fixture:` |
| `SimulatedJudgeFixture` | julgamento já pronto; `judge_engine_id` exige `fixture:`; `has_critical_alert` |
| `SimulatedPolicyGateResult` | gate SIMULADO (allowed/code/reason); não chama policy real |
| `OfflineCouncilInput` | entrada (prompt não vaza no repr) + fixtures + gate |
| `OfflineCouncilResult` | resultado serializável (session/policy/risk/candidates/anon/reviews/disagreement/arbiter/gate/audit/failure_code) |
| `OfflineCouncilSimulator` | `run(input)` — função pura e determinística |

## 5. Pipeline simulado

```text
RiskAssessment (nível + sensibilidade → cloud negada)
  → CouncilPolicy (modo; private → sem persistência; local → sem cloud)
  → AnswerCandidate[] (das fixtures) → anonymized[] (sem engine_id)
  → BlindReview[] (das fixtures; exclui autojulgamento quando há juiz limpo)
  → DisagreementReport (spread dos overalls: alto ⇒ requires_clarification)
  → ArbiterDecision (bloqueia em falha; senão seleção determinística)
  → SimulatedPolicyGateResult (negado ⇒ bloqueia)
  → CouncilAuditRecord[] (private_mode ⇒ persist_allowed=false)
```

Ordem determinística de falha: `COUNCIL_DISABLED` → sem candidato elegível
(`NO_ELIGIBLE_LOCAL_ENGINE` ou o `failure_code` do fixture que falhou) →
`INSUFFICIENT_JUDGES` (conflito total) → `ARBITER_UNSAFE_OUTPUT` (alerta crítico)
→ `JUDGE_DISAGREEMENT_HIGH` → `POLICY_GATE_DENIED`. Nenhuma exceção não tratada.

## 6. Regras de segurança implementadas

- Puro: sem I/O, sem rede, sem tempo/random, sem threads/subprocess.
- Sem policy/audit/vault reais; só importa `nomos.council.models` (stdlib + models).
- Fixtures obrigam prefixo `fixture:` (impossível passar um motor real por engano).
- Determinístico: mesma entrada ⇒ mesma saída (byte a byte no JSON).
- Invariantes MC1 preservadas: paranoid → local-only; sensível → cloud negada;
  privado → persistência negada; gate final exigido.
- Anonimização remove `engine_id` antes dos juízes; autojulgamento excluído
  quando há juiz limpo, senão fail-closed (`INSUFFICIENT_JUDGES`).
- Alerta crítico ⇒ bloqueia (`ARBITER_UNSAFE_OUTPUT`).
- Prompt nunca aparece em `repr` nem na serialização do resultado.

## 7. Testes adicionados

| Arquivo | Testes |
|---|---|
| tests/test_council_simulator.py | 17 (7 cenários obrigatórios + autojulgamento/insuficiência/alerta/falha/desligado + roundtrip/determinismo/prefixo/tipo) |
| tests/test_council_simulator_security.py | 9 (sem rede/subprocess/threading/asyncio/motor; sem FS; sem policy/vault/audit; prompt/fixture não vazam; só stdlib+models) |

Total novo: **26** (mínimo exigido: 20). Suíte completa: **577**. Todos os 20
nomes obrigatórios da missão estão presentes.

## 8. Não escopo (confirmado)

Sem motor real · sem roteador real · sem judge real · sem arbiter com LLM · sem
CLI · sem chat commands · sem persistência · sem cloud · sem policy/audit/vault
reais · sem rede/threads/subprocess/timers · sem PyPI/release/tag.

## 9. Riscos remanescentes

- O simulador prova o **fluxo e as invariantes**, mas usa fixtures fixas; a
  qualidade real de candidatos/juízes só aparece com motores locais (MC3).
- O gate aqui é **simulado**; a integração com o `policy.gate` real e o
  fail-closed sem aprovador entram na MC4.
- A redação real de segredos no audit (via `kernel/audit`) e a persistência
  controlada (modo privado no disco) entram na MC5.

## 10. Próximo passo recomendado

Iniciar a **Fase MC3 (local engine integration)** sob `implementation-loop-100`:
substituir apenas os `SimulatedEngineFixture` por geração de **motores locais**
(sem cloud, sem rede externa), mantendo juízes/árbitro/gate ainda simulados e
todas as invariantes já provadas.
