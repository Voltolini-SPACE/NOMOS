# NOMOS Audit Log HMAC Anchor v1

## 1. Status final

STATUS_FINAL=PASS_AUDIT_LOG_HMAC_ANCHORED

A lacuna de truncamento de cauda divulgada na auditoria foi reproduzida e
mitigada com uma âncora HMAC cuja chave vive no cofre. Todos os testes passam
e a verificação distingue os estados corretamente.

## 2. Baseline

| Item | Resultado |
|---|---|
| BASELINE_HEAD | 42d1530 |
| BASELINE_TAG | v1.2.0rc2-security-audited-1-g42d1530 |
| GIT_STATUS | CLEAN |
| GIT_FSCK | PASS |
| RUFF | PASS |
| PYTEST | PASS (503 antes → 520 depois) |
| COVERAGE | 84% |
| BUILD | PASS |
| DOUTOR | PASS |
| PYTHON_M_NOMOS_DOUTOR | PASS |
| AGENTES_LISTAR | PASS |
| LOGS_VERIFY_BASELINE | PASS (cadeia íntegra) |

## 3. Lacuna reproduzida

`test_audit_tail_truncation_not_detected_by_unkeyed_chain`: com 4 entradas
A→B→C→D, remover D deixa A→B→C, e `AuditLog.verify()` continua retornando
`(True, -1)`. A cadeia sem chave detecta modificação, reordenação e remoção do
MEIO — mas não o truncamento de cauda, e, por não ter segredo, poderia ser
reescrita inteira por quem tem escrita.

## 4. Modelo implementado

**Âncora HMAC** (`src/nomos/kernel/audit_anchor.py`): um checkpoint assinado
sobre o estado atual do log.

Corpo ancorado (`nomos.audit.anchor.v1`):

```json
{"schema":"nomos.audit.anchor.v1","entries_count":N,"chain_tip":"<sha256>",
 "log_id":"<hex>","created_at":<ts>,"hmac":"<hmac-sha256>"}
```

- **Chave**: 32 bytes aleatórios (`secrets`), guardada no COFRE como
  `__audit_hmac_key__` (Argon2id). Nunca em claro, nunca logada, nunca impressa
  em erro; acessada fail-closed. Sem rede/nuvem/telemetria.
- **HMAC-SHA256** sobre o corpo canônico; verificação em tempo constante
  (`hmac.compare_digest`).
- `criar_ancora` é idempotente e preserva o `log_id`; recusa ancorar cadeia já
  corrompida (não mascara corrupção anterior).
- **Verificação** (`verificar`) devolve um estado:

| Estado | Severidade | Quando |
|---|---|---|
| LOG_ANCHORED_VALID | PASS | cadeia + count + tip + HMAC conferem |
| LOG_LEGACY_UNANCHORED | WARN | sem chave e sem âncora (cadeia ok, tail não provado) |
| LOG_ANCHOR_UNVERIFIED | WARN | âncora presente, sem passphrase p/ checar HMAC |
| LOG_ANCHORED_INVALID | FAIL | HMAC inválido (adulteração/chave errada) |
| LOG_TAIL_TRUNCATED | FAIL | menos entradas que o ancorado, ou tip do ponto ancorado diverge |
| LOG_ANCHOR_MISSING | FAIL | chave existe no cofre mas a âncora sumiu |
| LOG_CHAIN_CORRUPTED | FAIL | a própria cadeia quebrou |

- **CLI**: `nomos logs verify` mostra o estado (WARN/PASS/FAIL); `--cofre`
  valida o HMAC. `nomos logs anchor` cria a âncora (gate A3 CRED_USE +
  passphrase), idempotente, auditado como `audit.ancorado` (só metadados).

**Evidência end-to-end** (smoke real): âncora válida ⇒ `[PASS] LOG_ANCHORED_VALID`
(rc 0); após remover a última linha ⇒ `[FAIL] LOG_TAIL_TRUNCATED` (rc 1);
`logs anchor` sem TTY ⇒ negado fail-closed (`[NOMOS-E002]`).

## 5. Testes adicionados

| Teste | Resultado |
|---|---|
| tail_truncation_not_detected_by_unkeyed_chain (baseline) | PASS |
| hmac_anchor_detects_tail_truncation | PASS |
| hmac_anchor_detects_rewritten_chain_without_key | PASS |
| anchor_tamper_fails | PASS |
| anchor_wrong_hmac_fails | PASS |
| anchor_count_mismatch_fails | PASS |
| anchor_tip_mismatch_fails | PASS |
| anchor_missing_key_fails_closed | PASS |
| legacy_unanchored_log_warns_not_passes | PASS |
| anchor_ausente_com_chave_e_missing | PASS |
| logs_anchor_legacy_is_idempotent | PASS |
| reancorar_apos_crescer_valida | PASS |
| audit_hmac_key_never_logged_or_printed | PASS |
| chain_corrupted_tem_prioridade | PASS |
| nao_ancora_cadeia_corrompida | PASS |
| logs_verify_reports_anchored_status (CLI) | PASS |
| logs_anchor_cli_creates_anchor (CLI parser) | PASS |

Total da suíte: **520** (17 novos). Ruff limpo. Build ok.

## 6. Compatibilidade com logs antigos

Log sem âncora e sem chave no cofre ⇒ `LOG_LEGACY_UNANCHORED` (**WARN**, nunca
PASS silencioso), com orientação para rodar `nomos logs anchor`. `logs anchor`
avisa explicitamente que logs antigos sem HMAC não provam a ausência de
truncamento anterior — a âncora cobre o estado atual em diante. Se a chave já
existe no cofre mas a âncora some, o estado é `LOG_ANCHOR_MISSING` (FAIL): o
atacante pode apagar a âncora, mas não a chave (cifrada), então a remoção é
detectada.

## 7. Segurança

- Sem chave hardcoded — gerada com `secrets.token_bytes(32)`.
- Sem plaintext — chave cifrada no cofre (Argon2id).
- Sem log de segredo — teste garante que a chave nunca aparece na âncora, no
  corpo devolvido nem no audit log.
- Sem cloud/rede/telemetria — puramente local.
- Fail-closed — sem passphrase/chave a âncora não vira PASS; cadeia corrompida
  tem prioridade; `logs anchor` sem TTY é negado.

## 8. Riscos remanescentes

1. **Janela pós-âncora**: entradas gravadas após a última âncora só têm a
   proteção da cadeia (modificação/reordenação/remoção-do-meio); o truncamento
   dessas entradas mais novas só é detectado após reancorar. `logs verify`
   sinaliza quantas entradas estão além da última âncora. Mitigação operacional:
   ancorar periodicamente (ex.: rotina/hook).
2. **Atacante com a passphrase** pode reancorar e forjar — inerente a qualquer
   esquema cuja chave o próprio usuário detém; fora do modelo de ameaça local.
3. A âncora é um checkpoint único por log; ancoragem contínua a cada append
   exigiria a passphrase sempre (incompatível com o append sem cofre) — decisão
   consciente de design.

## 9. Commits

| Commit | Descrição |
|---|---|
| ceaa55b | fix(audit): âncora HMAC ancorada no cofre contra truncamento de cauda |
| 2e027ee | test(audit): cobre truncamento, reescrita e adulteração da âncora HMAC |
| (este) | docs(audit): documenta o modelo de audit log ancorado |

## 10. Não escopo (confirmado)

Sem Conselho de Motores · sem PyPI · sem painel read-write · sem Obsidian · sem
novas features fora do audit log · sem mover tags · sem force-push.

## 11. Próximo passo recomendado

Criar nova tag pós-hardening do audit log (ex.: `v1.2.0rc3-audit-anchored`),
sem mover as tags anteriores, após o CI verde nos três sistemas.
