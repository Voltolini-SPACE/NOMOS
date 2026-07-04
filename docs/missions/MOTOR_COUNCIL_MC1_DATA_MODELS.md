# MOTOR COUNCIL MC1 — DATA MODELS ONLY

## 1. Status final

STATUS_FINAL=PASS_MOTOR_COUNCIL_MC1_DATA_MODELS

Modelos de dados puros criados, com invariantes de segurança por construção e
31 testes novos. Nenhuma execução de motor, I/O, rede, persistência, CLI ou
chat command.

## 2. Baseline

| Item | Resultado |
|---|---|
| BASELINE_HEAD | 030244d |
| BASELINE_TAG | v1.2.0rc3-audit-anchored-2-g030244d |
| GIT_STATUS | CLEAN (antes dos commits) |
| GIT_FSCK | PASS |
| RUFF | PASS |
| PYTEST | PASS_520 → PASS_551 |
| BUILD | PASS (wheel inclui `nomos/council/`) |
| DOUTOR | PASS |
| PYTHON_M_NOMOS_DOUTOR | PASS |
| LOGS_VERIFY | PASS (LEGACY_UNANCHORED esperado) |

## 3. Escopo

```text
DATA_MODELS_ONLY=true
ENGINE_EXECUTION=false
PERSISTENCE=false
CLI=false
CHAT_COMMANDS=false
```

## 4. Modelos criados

| Modelo | Schema | Papel |
|---|---|---|
| CouncilMode (enum) | — | fast / balanced / critical / paranoid |
| CouncilRiskLevel (enum) | — | A0–A6 (alinhado ao Policy Gate; sem executar gate) |
| CouncilConfidence (enum) | — | low / medium / high |
| CouncilDisagreementLevel (enum) | — | low / medium / high |
| CouncilFailureCode (enum) | — | 11 estados de falha da spec |
| CouncilSession | nomos.council.session.v1 | estado da sessão + `persist_allowed` |
| CouncilPolicy | nomos.council.policy.v1 | política do conselho (gate final exigido) |
| RiskAssessment | nomos.council.risk.v1 | nível + sensibilidade + `cloud_allowed` |
| AnswerCandidate | nomos.council.candidate.v1 | candidato + `anonymized()` |
| BlindReview | nomos.council.review.v1 | review + `redacted_public()` + `is_self_judging` |
| JudgeScore | nomos.council.judge_score.v1 | rubrica 0–5 + flags |
| ArbiterDecision | nomos.council.arbiter.v1 | decisão + `requires_policy_gate` |
| DisagreementReport | nomos.council.disagreement.v1 | divergência + `requires_clarification` |
| CouncilAuditRecord | nomos.council.audit.v1 | registro + `persist_allowed` |

Todos com `to_dict / from_dict / to_json / from_json` determinísticos.

## 5. Regras de segurança implementadas (por construção)

- `paranoid` ⇒ `local_only=True` e `cloud_allowed=False` (session e policy).
- `local_only=True` ⇒ `cloud_allowed=False` (e `allow_sensitive_data_to_cloud=False`).
- `private_mode=True` ⇒ `persist_allowed=False` (session e audit record).
- `contains_sensitive_data=True` ⇒ cloud negada (`cloud_allowed` False +
  `cloud_denied_reason`).
- `require_final_policy_gate=True` e `allow_sensitive_data_to_cloud=False` por padrão.
- `AnswerCandidate.anonymized()` remove `engine_id` (autoria) antes do julgamento.
- `BlindReview.redacted_public()` remove `judge_engine_id`; `is_self_judging`
  detecta juiz == autor.
- `repr` de `AnswerCandidate`, `ArbiterDecision` e `CouncilAuditRecord` NÃO
  imprime conteúdo/metadata (redação por design).
- `JudgeScore` valida cada critério como inteiro 0–5; fora disso, falha.
- Schema/enum inválidos ⇒ `CouncilModelError` (fail-closed).

## 6. Testes adicionados

| Arquivo | Testes |
|---|---|
| tests/test_council_models.py | 19 (contratos: roundtrip, invariantes, anonimização, blind review, score, arbiter, disagreement, audit, schema/enum) |
| tests/test_council_model_security.py | 12 (repr redige; invariantes; autojulgamento; sem import de rede/motor; só stdlib) |

Total novo: **31** (mínimo exigido: 19). Suíte completa: **551**.

Cobre todos os nomes obrigatórios da missão: session_roundtrip_json,
policy_local_only_denies_cloud, policy_defaults_final_gate_required,
paranoid_mode_forces_local_only, risk_sensitive_data_denies_cloud,
candidate_anonymized_removes_engine_id, candidate_repr_redacts_content,
blind_review_redacted_removes_judge_engine_id, blind_review_detects_self_judging,
judge_score_rejects_out_of_range, judge_score_roundtrip_json,
arbiter_requires_policy_gate_by_default, disagreement_high_requires_clarification,
audit_private_mode_disables_persist, audit_repr_redacts_metadata,
invalid_schema_rejected, invalid_enum_rejected,
models_do_not_import_network_modules, models_do_not_import_engine_modules.

## 7. Não escopo (confirmado)

- Sem execução de motor · sem roteador funcional · sem judge/arbiter reais.
- Sem CLI (`nomos conselho`) · sem chat command (`/conselho`).
- Sem persistência · sem cloud · sem policy gate real.
- Sem alteração de policy / audit / vault / agents / skills / motores.
- Sem rede, sem threads/processos, sem I/O.
- Sem PyPI, sem release, sem tag.

## 8. Riscos remanescentes

- As invariantes valem no nível de modelo; a **fase MC4** ainda precisa ligar o
  Policy Gate real antes de qualquer resposta ao usuário.
- A anonimização é de campo (`engine_id`→`ANON`); a fase de execução (MC3) deve
  garantir que o mapa autor↔alias fique fora do que chega ao juiz.
- Os modelos aceitam texto arbitrário em `content`/`metadata`; a redação real de
  segredos (via `kernel/audit`) entra na fase de integração de auditoria (MC5).

## 9. Próximo passo recomendado

Iniciar a **Fase MC2 (offline simulator)** sob `implementation-loop-100`: um
simulador do pipeline com **fixtures fixas** (sem LLM real) que exercita os
estados e as invariantes destes modelos, ainda sem integrar motores locais.
