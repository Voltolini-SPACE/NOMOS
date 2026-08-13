# FASE 10 — TIMEOUT (regressão)

**20 passed / 2 skipped** nos testes de timeout/deadline/prazo.

| Superfície | Coberto | Como |
|---|---|---|
| nó direto do runtime | ✅ | `CapabilityContext.exigir_prazo()` em `Adapter._coerente` |
| adapter de filesystem | ✅ | `test_n11_escopo_expirado_pelo_deadline` — nem começa |
| execução de script | ✅ | `test_timeout_mata_o_processo` (kill de grupo) + `test_deadline_do_no_limita_o_script` |
| ocorrência de scheduler | ⚠️ **indireto** | o deadline chega pela ponte do wiring; **sem teste dedicado** |
| alert sink | ❌ | **não coberto** — `AuditAlertSink` escreve em arquivo local, sem prazo |

## Retry após timeout
`EfeitoTimeout` classifica explicitamente:
```
TIMED_OUT_NO_EFFECT · TIMED_OUT_EFFECT_UNKNOWN · TIMED_OUT_EFFECT_CONFIRMED
```
`EFEITO_DESCONHECIDO` **nunca** autoriza retry, nem para capacidade
idempotente: idempotência diz que repetir é seguro, não que um efeito parcial
foi revertido. São coisas diferentes, e o teste
`test_efeito_desconhecido_nao_e_idempotente_por_definicao` fixa isso.

`script-rodar` é registrado com `idempotente=False`, então um timeout dele
jamais é repetido automaticamente.

```
NODE_HARD_TIMEOUT=PASS
SCHEDULER_TIMEOUT=PARCIAL (indireto, sem teste dedicado)
UNKNOWN_EFFECT_RETRY=0
ALERT_SINK_TIMEOUT=NAO_COBERTO
```
