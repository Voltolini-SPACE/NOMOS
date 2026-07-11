# BACKLOG do loop — fila de missões

Ordem = prioridade. O loop pega a primeira `pronta` e executa **uma por rodada**.
Estados: `pronta` · `em curso` · `feita — aguardando push humano` · `bloqueada` · `entregue`.
Quem adiciona/reordena missões: o humano (fonte: ROADMAP_4, docs/missions, achados do próprio loop).

| ID | Missão | Critério de aceite | Estado |
|----|--------|--------------------|--------|
| L1 | Calibração: teste que valida a própria estrutura do loop | `tests/test_loop_estrutura.py` verifica: existência dos 4 arquivos de `loop/` + 2 agentes; LOOP_LOG contém bloco ESTADO ATUAL; BACKLOG contém tabela com estados válidos; LOOP_PROMPT contém as proibições (`push`, `main`). pytest + ruff 100% | pronta |
| L2 | Guardião no CI: job que roda o teste de estrutura do loop | Passo no `ci.yml` executando o teste de L1 (mesmo espírito da REGRA MC33) | pronta |
| LP1 | `nomos loop iniciar` — scaffold do loop de produto (spec: docs/missions/MC35_NOMOS_LOOP_PRODUTO_SPEC.md §5) | Cria loop/{PROJETO,BACKLOG,LOOP_LOG}.md com templates; idempotente; testes de scaffold; pytest+ruff 100% | pronta |
| LP2 | `nomos loop status` | Lê ESTADO/BACKLOG reais; saída amigável; erro claro se não iniciado | pronta |
| LP3 | `nomos loop rodada --dry-run` | Escolhe missão, PLANO legível (passos + nível A + arquivos), nada executa; trava + aborto por árvore suja testados | pronta |
| LP4 | Execução gateada (consent + audit) | Aprovação por rodada via ConsentRegistry; evidência HMAC via AuditLog; fail-closed em CI | pronta |
| LP5 | Revisor independente (council) | Trace auditável; FAIL bloqueia commit; teste com falha injetada | pronta |
| LP6 | `nomos loop agendar` + docs + site | Rotina criada via rotinas.py; docs de usuário; site reflete produto (MC33) | pronta |
| LP7 | Aviso de fim de rodada (local + conector opt-in) | LOOP_LOG sempre; aviso externo atrás de gate; falha de aviso não quebra rodada | pronta |
| LP8 | `nomos loop entregar` (pacote p/ push humano) | Diff + evidências + commit/PR sugerido + passo a passo; agente nunca envia | pronta |

## Regras da fila
- Missão boa = cabe em 1 rodada, tem critério de aceite testável, não exige decisão estrutural.
- Missão grande → o humano quebra em missões menores antes de marcar `pronta`.
- `bloqueada` sempre carrega o motivo/pergunta no LOOP_LOG.
