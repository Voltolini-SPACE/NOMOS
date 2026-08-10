# FASE 1 — WIRE ORQUESTRACAO AO RUNTIME REAL

Commit: `2bcfa5b feat(nomos): wire orchestration into governed runtime`

## O estado que foi eliminado
`src/nomos/orquestracao/` tinha 117 testes passando e **zero referências em
`src/` fora do próprio pacote**. Biblioteca validada, não capacidade
operacional. Agora tem caller de produção.

## O que foi construído
`src/nomos/runtime/governado.py` — `RuntimeGovernado`:

```
intenção → planejar() → PlanoTipado → para_grafo() → GrafoTarefas
        → Orquestrador (policy.decide + gate A0–A6 por nó)
        → adapter nativo (AgentToolBoundary) → evidência/auditoria
```

`src/nomos/cli.py` — `nomos orquestrar <objetivo> [--passos JSON] [--executar]`.
Dry-run por padrão: sem `--executar`, planeja e não roda nada.

## Defeito de segurança encontrado e corrigido durante o wiring

`recuperacao.executar` decidia retry lendo `no.idempotente` — campo do PLANO.
`planejar()` já derivava do registro (com comentário explicando o ataque), mas
**um grafo montado à mão contornava o planejador**: bastava `No("w",
"arquivo_escrever", idempotente=True)` para uma capacidade mutante ganhar
retry. Uma aprovação humana viraria N efeitos reais.

Correção em três camadas:
1. `GrafoTarefas` recusa (`ErroGrafo`) nó que reivindique mais idempotência que
   a capacidade tem no registro. Reivindicar menos segue permitido (conservador).
2. `recuperacao.executar(..., *, idempotente)` é autoritativo e **não lê mais**
   `no.idempotente`; ausente ⇒ False (fail-closed).
3. `Orquestrador._rodar` sempre passa `registro.idempotente_de(no.ferramenta)`.

Verificado por mutação: removendo (1), três testes falham.

## Requisitos da fase — evidência

| # | Requisito | Evidência |
|---|---|---|
| 1 | caller real em `src/` | `cli.py::cmd_orquestrar` + `runtime/governado.py` |
| 2 | intenção→tarefas→deps→capability→ordem→exec→recovery→evidência | `test_dag_valido_executa_em_ordem_topologica`, trilha de auditoria |
| 3 | planner não declara o próprio risco | `test_categoria_vem_do_registro_nao_do_plano` |
| 4 | risco vem do registro/policy | `registro.categoria_de()` é a única fonte |
| 5 | nenhum nó executa fora do boundary | `executores_nativos` embrulha tudo em `AgentToolBoundary` |
| 6 | mesmos gates A0–A6 | `Orquestrador` chama `policy.decide` + `gate` por nó |
| 7 | ciclo falha deterministicamente | `test_ciclo_falha_deterministicamente_e_nada_executa` |
| 8 | capability inexistente falha closed | `test_capability_inexistente_falha_fechada` |
| 9 | planner malformado falha closed | `test_planner_malformado_falha_fechado` |
| 10 | recovery não vira retry-then-allow | `test_deny_nao_vira_retry_then_allow` (tentativas=0) |
| 11 | circuit breaker não cria bypass | `test_circuito_abre_e_nao_vira_bypass` |
| 12 | nenhum shell genérico | `test_nenhum_executor_generico_no_runtime` |

## Execução real (não simulada)
```
$ nomos orquestrar "ler e diagnosticar" --executar --passos '[...]'
plano: 2 passo(s) · risco A0
  ✅ a: OK
  ✅ b: OK
missão concluída — todos os nós OK
```
Com dependência quebrada: `❌ a: FALHOU` → `⏸ b: BLOQUEADO`.
Sem TTY, capacidade mutante: `⛔ w: NEGADO — ação sensível: exige aprovação explícita`.
Ciclo: `[NOMOS-E003] grafo inválido: ciclo de dependências envolvendo: a, b` (exit 3).

## Gate FASE 1
```
ORCHESTRATION_REAL_CALLER=TRUE
ORCHESTRATION_ZERO_BYPASS=TRUE   (no caminho do runtime; ver FASE2 p/ rotas legadas)
ORCHESTRATION_TESTS=PASS         (25 novos + 117 do pacote)
```
