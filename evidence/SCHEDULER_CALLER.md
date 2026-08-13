# FASES 2 — CALLER DE PRODUÇÃO DO SCHEDULER

Commit `a120123` · `src/nomos/runtime/agendador.py` + `src/nomos/cli.py`

## O fio
```
CLI (nomos scheduler | nomos orquestrar --scheduler)
  → AgendadorGovernado
  → Scheduler (store: NOMOS_HOME/scheduler/jobs.db)
  → registrar_scheduler()  →  RegistroCapacidades AUTORITATIVO
```

`registrar_scheduler` saiu de **0 callers** para 2 caminhos de produção:
`cli.cmd_scheduler` (via `AgendadorGovernado.preparar()`) e
`cli.cmd_orquestrar --scheduler`.

## Ativação é intencional, nunca por import
`AgendadorGovernado.__init__` não registra nada. `preparar()` é o passo
explícito, e ele passa pelo gate: registrar é `A5_SKILL_INSTALL`, exige
aprovador e é auditado (`registro.capacidade.registrada` +
`agendador.preparado` na trilha).

Sem aprovador ⇒ `ErroRuntime` na construção.
Aprovador que nega ⇒ `ErroRegistro`, e `capacidades == []`, `_preparado == False`
(sem meia-capacidade registrada).

## Sem registry/policy/executor paralelo
As capacidades entram no MESMO `RegistroCapacidades` que o planner e o PDP
consultam — provado por `test_registro_e_o_MESMO_que_o_planner_consulta`, que
planeja um passo `sched-listar` e obtém categoria do registro.

Um teste estrutural proíbe `scheduler_registry`, `scheduler_policy` e
`scheduler_executor` como identificadores.

## Verificação por CLI real
```
$ nomos scheduler listar --raiz <ws>
nenhum job agendado.

$ nomos orquestrar "x" --scheduler
[NOMOS-E010] --executavel/--scheduler exigem pelo menos um --raiz
```

## Gates
```
SCHEDULER_REGISTRATION_PRODUCTION_CALLER = 2
SCHEDULER_PARALLEL_REGISTRY = FALSE
```
