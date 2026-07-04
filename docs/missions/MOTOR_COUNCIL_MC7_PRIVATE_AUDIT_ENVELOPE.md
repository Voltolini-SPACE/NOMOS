# MOTOR COUNCIL MC7 — PRIVATE MODE + AUDIT ENVELOPE SPEC/DRY-RUN

## 1. Status final

STATUS_FINAL=PASS_MOTOR_COUNCIL_MC7_PRIVATE_AUDIT_ENVELOPE

Envelopes de auditoria em dry-run criados, provando `private_mode=true ⇒
persist_allowed=false` e redação metadata-only. 31 testes novos. Sem audit/vault/
policy/approval reais, sem motor, HTTP, subprocess, cloud, FS, env, tempo ou
random.

## 2. Baseline

| Item | Resultado |
|---|---|
| BASELINE_HEAD | 8e1f6f4 |
| BASELINE_TAG | v1.2.0rc3-audit-anchored-23-g8e1f6f4 |
| GIT_STATUS | CLEAN (antes dos commits) |
| GIT_FSCK | PASS |
| RUFF | PASS |
| PYTEST | PASS_693 → PASS_724 |
| BUILD | PASS_IN_TMP_SANDBOX_FS_QUIRK (wheel `nomos-1.3.0rc15` em `/tmp`, inclui `audit_envelope.py`) |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | PASS (LEGACY_UNANCHORED esperado) |

`python -m build` no diretório montado estoura `RecursionError` na limpeza de
tempdir do backend (quirk do FS fuse); o pacote compila em `/tmp` e o job `smoke`
do CI builda nos 3 SOs.

## 3. Escopo

```text
AUDIT_ENVELOPE_DRY_RUN=true
REAL_AUDIT_WRITE=false
REAL_ENGINE_EXECUTION=false
CLOUD=false
NETWORK=false
SUBPROCESS=false
PERSISTENCE=false
PRIVATE_MODE_ENFORCED=true
```

## 4. O que foi criado

| Símbolo | Papel |
|---|---|
| `CouncilAuditEventType` | 12 eventos (SESSION_STARTED … AUDIT_DRY_RUN_BLOCKED) |
| `CouncilAuditRedactionProfile` | metadata-only; `for_private()` ⇒ redação máxima |
| `CouncilAuditEnvelope` | envelope dry-run; `would_write_audit=false`; metadata redigida |
| `CouncilAuditDryRunResult` | resultado; `allowed=false` se sensível/private-persist |
| `CouncilAuditEnvelopeBuilder` | `build_for_result` + `validate`; metadata-only |
| `CouncilAuditEnvelopeFailure` / `AuditEnvelopeFailureCode` | 6 códigos AUDIT_ENVELOPE_* |
| `run_offline_council_with_audit_envelope(...)` | integração com o resultado simulado |

## 5. Audit envelope dry-run

`CouncilAuditEnvelope` representa um evento futuro do audit. Nesta fase,
`dry_run=true` e `would_write_audit=false` são forçados na construção — nenhuma
escrita real é possível. `to_dict`/`to_json`/`repr` sempre passam a metadata por
um redator que substitui chaves e valores sensíveis por `[REDIGIDO]`.

## 6. Redaction profile

`CouncilAuditRedactionProfile` exige `redact_content=True` e `redact_prompt=True`
(erro se falso). `for_private()` liga também `redact_scores_detail=True`
(redação máxima). O builder embute o perfil na metadata (metadata-only) e nunca
inclui prompt, conteúdo de candidato/final ou engine_id.

## 7. Private mode

`private_mode=true` força `persist_allowed=false` no envelope (construção) e o
builder gera todos os envelopes com `persist_allowed=false`. A validação
rejeita qualquer envelope que, em modo privado, declare `persist_allowed=true`
(`AUDIT_ENVELOPE_PRIVATE_PERSIST_DENIED`). Um evento `PRIVATE_MODE_ENFORCED` é
adicionado.

## 8. Integração com pipeline

`run_offline_council_with_audit_envelope(offline_result, *, private_mode,
extra_metadata, builder)` lê o resultado já simulado (contagens de candidatos/
reviews, failure_code), monta envelopes metadata-only e devolve o
`CouncilAuditDryRunResult`. **Não altera `run()`**; não chama audit real; não
grava em disco. `extra_metadata` existe só para exercitar o bloqueio de metadata
sensível nos testes.

## 9. Decisões fail-closed

| Situação | failure_code |
|---|---|
| metadata com chave/valor sensível | AUDIT_ENVELOPE_SENSITIVE_METADATA |
| envelope declara `would_write_audit=true` | AUDIT_ENVELOPE_REAL_WRITE_FORBIDDEN |
| envelope `redacted=false` | AUDIT_ENVELOPE_NOT_REDACTED |
| modo privado com `persist_allowed=true` | AUDIT_ENVELOPE_PRIVATE_PERSIST_DENIED |

## 10. Regras de segurança implementadas

- `dry_run=true`, `would_write_audit=false` sempre; nenhuma escrita real.
- `private_mode=true` ⇒ `persist_allowed=false`.
- Metadata só contagens/failure_code; prompt/conteúdo/engine_id/segredo/token
  nunca aparecem em `to_dict`/`to_json`/`repr`/`warnings`.
- Módulo **não importa** rede/cloud/SDK/motor/subprocess/threading/asyncio;
  **não toca** FS; **não usa** env/`time`/`datetime.now`/`random`.
- Sem policy/vault/audit/approval reais; só importa `nomos.council.models`.
- Determinístico.

## 11. Testes adicionados

| Arquivo | Testes |
|---|---|
| tests/test_council_audit_envelope.py | 23 (profile/envelope/dry-run-result/builder/integração) |
| tests/test_council_audit_envelope_security.py | 8 (sem rede/subprocess/asyncio/SDK/motor/FS/env/time/random; sem policy/vault/audit/approval) |

Total novo: **31** (mínimo exigido: 30). Suíte completa: **724**. Todos os 30
nomes obrigatórios da missão estão presentes.

## 12. Não escopo (confirmado)

Sem audit real · sem vault real · sem policy real · sem approval real · sem motor
real · sem Ollama · sem subprocess · sem HTTP · sem CLI · sem chat commands · sem
persistência · sem cloud · sem rede · sem PyPI/release/tag.

## 13. Riscos remanescentes

- O envelope é **dry-run**; a integração com o `kernel/audit` real (cadeia +
  âncora HMAC) só ocorre numa fase futura, mantendo redação e modo privado.
- A lista de chaves sensíveis é explícita; um nome de campo novo e não previsto
  poderia escapar — recomenda-se, na integração real, reusar o `redact` do
  kernel (por padrão + campo), que já é auditado.

## 14. Próximo passo recomendado

Iniciar a **Fase MC8 — Council Orchestrator SPEC/DRY-RUN** sob
`implementation-loop-100`, compondo provider + adapter + harness + gate + audit
envelope num único fluxo determinístico, ainda **sem motor real**, provando que a
ordem de checagens (local-only → gate → envelope) é fail-closed de ponta a ponta.
