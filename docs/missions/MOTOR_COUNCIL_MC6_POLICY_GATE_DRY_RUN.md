# MOTOR COUNCIL MC6 — POLICY GATE INTEGRATION SPEC/DRY-RUN

## 1. Status final

STATUS_FINAL=PASS_MOTOR_COUNCIL_MC6_POLICY_GATE_DRY_RUN

Integração com o Policy Gate A0–A6 em SPEC/DRY-RUN. Toda resposta final simulada
passa pelo gate antes de sair; só é liberada com `allowed=true`. 30 testes novos.
Sem policy/approval/vault/audit reais, sem motor, HTTP, subprocess, cloud, FS,
env, tempo ou random.

## 2. Baseline

| Item | Resultado |
|---|---|
| BASELINE_HEAD | f7f8391 |
| BASELINE_TAG | v1.2.0rc3-audit-anchored-20-gf7f8391 |
| GIT_STATUS | CLEAN (antes dos commits) |
| GIT_FSCK | PASS |
| RUFF | PASS |
| PYTEST | PASS_663 → PASS_693 |
| BUILD | PASS_IN_TMP_SANDBOX_FS_QUIRK (wheel `nomos-1.3.0rc14` em `/tmp`, inclui `policy_gate.py`) |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | PASS (LEGACY_UNANCHORED esperado) |

`python -m build` no diretório montado estoura `RecursionError` na limpeza de
tempdir do backend (quirk do FS fuse); o pacote compila em `/tmp` e o job `smoke`
do CI builda nos 3 SOs.

## 3. Escopo

```text
POLICY_GATE_DRY_RUN=true
REAL_POLICY_GATE=false
REAL_APPROVAL=false
REAL_ENGINE_EXECUTION=false
CLOUD=false
NETWORK=false
SUBPROCESS=false
PERSISTENCE=false
AUDIT_REAL=false
```

## 4. O que foi criado

| Símbolo | Papel |
|---|---|
| `CouncilGateRequest` | pedido (session_id, risco, flags, `final_content_chars`); sem conteúdo bruto |
| `CouncilGateDecision` | `dry_run=true`, `would_call_real_policy=false`, `would_request_approval=false` |
| `FinalResponseEnvelope` | envelope final; sem conteúdo se negado; `content_redacted` |
| `CouncilPolicyGateDryRun` | gate simulado A0–A6, determinístico, fail-closed |
| `CouncilGateFailure` / `GateFailureCode` | 8 códigos GATE_* |
| `CouncilGateRisk` / `gate_risk_of()` | LOW(A0/A1)/MEDIUM(A2)/HIGH(A3–A5)/DESTRUCTIVE(A6) |
| `run_offline_council_with_policy_gate(...)` | integração: resultado simulado → gate → envelope |

## 5. Gate dry-run

`CouncilPolicyGateDryRun.evaluate(request)` aplica regras determinísticas e nunca
toca policy/approval/vault/audit reais. `dry_run`, `would_call_real_policy` e
`would_request_approval` são forçados na construção da decisão — não há como o
gate desta fase chamar algo real.

## 6. Final response envelope

`FinalResponseEnvelope` carrega a decisão do gate e o veredito. Se o gate negar,
`blocked=true` e `content=None`. O conteúdo, quando liberado, fica no atributo
mas **nunca é serializado** (`to_dict` sempre `content=null`) nem aparece no
`repr` (redação). `private_mode` ⇒ `persist_allowed=false`.

## 7. Decisões fail-closed

| Regra | Condição | failure_code |
|---|---|---|
| 7.1 | `arbiter_blocked=true` | GATE_ARBITER_BLOCKED |
| 7.2 | `has_final_content=false` | GATE_EMPTY_FINAL_CONTENT |
| 7.3 | `risk_level=A6` | GATE_A6_DENIED |
| 7.4 | `requires_human_approval=true` | GATE_REQUIRES_APPROVAL (would_request_approval=false) |
| 7.5 | `contains_sensitive_data=true` | GATE_SENSITIVE_DATA_REQUIRES_STRICT_MODE |
| 7.7 | `risk_level ∈ {A3,A4,A5}` | GATE_HIGH_RISK_DRY_RUN_ONLY |
| 7.6 | A0/A1/A2, sem os acima | `allowed=true`, failure_code=null |

## 8. Integração com simulador

`run_offline_council_with_policy_gate(offline_result, *, requires_human_approval,
contains_sensitive_data, gate)` lê o resultado já simulado (MC2/MC3/MC4), monta
um `CouncilGateRequest` a partir da `ArbiterDecision` e da `session`, avalia no
gate dry-run e devolve o `FinalResponseEnvelope`. **Não altera `run()`**; não
chama policy/approval reais; gate negado ⇒ envelope sem conteúdo; modo privado ⇒
`persist_allowed=false`.

## 9. Regras de segurança implementadas

- Toda resposta final passa pelo gate; sem bypass para liberar sem gate.
- `dry_run=true` e nenhuma policy/approval/mutation real.
- Módulo **não importa** rede/cloud/SDK/motor/subprocess/threading/asyncio;
  **não toca** FS; **não usa** env/`time`/`datetime.now`/`random`.
- Sem policy/vault/audit/approval reais; só importa `nomos.council.models`.
- Determinístico; conteúdo final nunca vaza em repr/serialização.

## 10. Testes adicionados

| Arquivo | Testes |
|---|---|
| tests/test_council_policy_gate_dry_run.py | 21 (request/decision/envelope/regras/integração) |
| tests/test_council_policy_gate_security.py | 9 (sem rede/subprocess/asyncio/SDK/motor/FS/env/time/random; sem policy/vault/audit/approval) |

Total novo: **30** (mínimo exigido: 28). Suíte completa: **693**. Todos os 28
nomes obrigatórios da missão estão presentes.

## 11. Não escopo (confirmado)

Sem policy real · sem approval real · sem motor real · sem Ollama · sem
subprocess · sem HTTP · sem roteador real · sem juiz real · sem árbitro real com
LLM · sem CLI · sem chat commands · sem persistência · sem cloud · sem rede · sem
audit/vault reais · sem PyPI/release/tag.

## 12. Riscos remanescentes

- O gate é **dry-run**; a integração com o `policy.gate` A0–A6 real (fail-closed
  sem aprovador) só ocorre numa fase futura explicitamente aprovada.
- A regra de dado sensível é conservadora (bloqueia sempre nesta fase); a
  liberação com modo estrito local só será desenhada quando houver execução real.

## 13. Próximo passo recomendado

Iniciar a **Fase MC7 — Private Mode + Audit Envelope SPEC/DRY-RUN** sob
`implementation-loop-100`, ainda sem audit real, para provar que candidatos/
reviews/decisões **não persistem em modo privado** e que os logs futuros serão
redigidos (metadados apenas).
