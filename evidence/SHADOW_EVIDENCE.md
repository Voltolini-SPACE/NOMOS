# FASE 7 — SHADOW MODE · **NÃO EXECUTADA**

Status: `NOT_STARTED`. O NOMOS não foi executado em paralelo a Hermes/OpenClaw.

Precondições não cumpridas, em cascata:
- FASE 3 (adapters) não executada ⇒ o NOMOS não consegue processar a mesma
  classe de workload;
- FASE 6 (daemon) não executada ⇒ não há processo para observar em paralelo.

Rodar "shadow" sem essas duas produziria comparação vazia — decision parity
medida sobre um conjunto de capacidades que o NOMOS não tem. Seria um número
bonito e falso.

```
SHADOW_EXECUTED=FALSE
SHADOW_EXTERNAL_EFFECTS=0   (trivialmente: nada rodou)
decision_parity / capability_parity / planner_parity / policy_parity /
error_parity / latency / audit_completeness = NÃO MEDIDOS
```

## Regra que continua valendo quando for executado
Shadow **não pode gerar segundo efeito externo**. Para operação mutante:
dry-run, executor interceptado, shadow sink e comparação determinística.
Hermes/OpenClaw permanecem os executores oficiais durante toda a janela.
