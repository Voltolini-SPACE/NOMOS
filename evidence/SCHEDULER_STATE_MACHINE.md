# FASE 3 — MÁQUINA DE ESTADOS DO SCHEDULER

```
CREATED ──► SCHEDULED ──► RUNNING ──► SUCCEEDED ──┐
   │            │            │           │        │
   │            │            │           └─► SCHEDULED (recorrente)
   │            │            └─► FAILED ──────────┘
   │            │
   ├────────────┴─► DISABLED ──► SCHEDULED
   │
   └──────────────► CANCELLED   (TERMINAL — não ressuscita)
```

`TRANSICOES` é **allowlist**: o que não está declarado é recusado com
`ErroScheduler`, e a recusa é auditada (`scheduler.transicao.negada`).

| De | Para permitidos |
|---|---|
| CREATED | SCHEDULED, DISABLED, CANCELLED |
| SCHEDULED | RUNNING, DISABLED, CANCELLED |
| RUNNING | SUCCEEDED, FAILED, CANCELLED |
| SUCCEEDED | SCHEDULED, DISABLED, CANCELLED |
| FAILED | SCHEDULED, DISABLED, CANCELLED |
| DISABLED | SCHEDULED, CANCELLED |
| CANCELLED | ∅ |

`CREATED → RUNNING` é proibido de propósito: executar sem passar por SCHEDULED
seria pular o agendamento.

## Quatro conceitos separados
```
JobDefinition  o quê/quando (persistente)     JobInstance   UMA ocorrência
JobState       ponto do ciclo                 JobExecution  UMA tentativa
```
Confundir definição com execução é a origem clássica do efeito duplicado: "o
job rodou" não diz QUAL ocorrência rodou, e o restart repete.
