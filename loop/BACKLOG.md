# BACKLOG do loop — fila de missões

Ordem = prioridade. O loop pega a primeira `pronta` e executa **uma por rodada**.
Estados: `pronta` · `em curso` · `feita — aguardando push humano` · `bloqueada` · `entregue`.
Quem adiciona/reordena missões: o humano (fonte: ROADMAP_4, docs/missions, achados do próprio loop).

| ID | Missão | Critério de aceite | Estado |
|----|--------|--------------------|--------|
| L1 | Calibração: teste que valida a própria estrutura do loop | `tests/test_loop_estrutura.py` verifica: existência dos 4 arquivos de `loop/` + 2 agentes; LOOP_LOG contém bloco ESTADO ATUAL; BACKLOG contém tabela com estados válidos; LOOP_PROMPT contém as proibições (`push`, `main`). pytest + ruff 100% | pronta |
| L2 | Guardião no CI: job que roda o teste de estrutura do loop | Passo no `ci.yml` executando o teste de L1 (mesmo espírito da REGRA MC33) | pronta |
| L3 | (humano define — sugerido: menor missão da Trilha P do ROADMAP_4) | — | bloqueada |

## Regras da fila
- Missão boa = cabe em 1 rodada, tem critério de aceite testável, não exige decisão estrutural.
- Missão grande → o humano quebra em missões menores antes de marcar `pronta`.
- `bloqueada` sempre carrega o motivo/pergunta no LOOP_LOG.
