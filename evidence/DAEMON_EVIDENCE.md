# FASE 6 — DAEMON · **NÃO EXECUTADA**

Status: `NOT_STARTED`. Nenhum serviço foi construído, instalado, carregado ou
removido. Nenhum LaunchAgent criado ou alterado.

A FASE 6 era explicitamente condicionada: *"Somente depois das fases anteriores
verdes."* A FASE 3 (adapters) não foi executada, então a precondição não se
cumpriu. Construir o daemon antes dos adapters produziria um serviço que sobe,
responde health e **não sabe fazer nada que Hermes/OpenClaw fazem** — exatamente
o "terceiro runtime paralelo" que o Princípio 1 proíbe.

## Gates — todos pendentes, nenhum inferido
```
DAEMON_INSTALLABLE=NOT_STARTED
DAEMON_REMOVABLE=NOT_STARTED
SINGLE_INSTANCE=NOT_STARTED
CRASH_RECOVERY=NOT_STARTED
REBOOT_RECOVERY=NOT_STARTED     (e mesmo se construído, seria
                                 PENDING_DIRECT_EVIDENCE sem reboot físico)
ROLLBACK_TESTED=NOT_STARTED     (o runbook existe; o cenário de daemon não)
```

## Requisitos registrados para quando for construído
single instance · PID ownership explícito · health · readiness · logs
estruturados · restart · crash recovery · startup após reboot · isolamento de
segredo · retry limitado · sem restart storm · shutdown limpo.

**Porta:** endpoint próprio de shadow. Não ocupar `:9119` (Hermes) nem `:18789`
(OpenClaw) — o Princípio 6 proíbe mudança permanente de porta antes do gate de
canary/cutover.
