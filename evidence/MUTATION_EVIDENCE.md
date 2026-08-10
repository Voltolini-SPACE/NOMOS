# FASE 11 — MUTATION EVIDENCE

## Harness verificado ANTES de confiar no resultado
```
pytest 9.1.1
suites: test_absorption04_agenda.py · test_absorption04_ticker_script.py
        test_absorption03_scheduler.py
collect: 105 tests collected
exit code baseline: 0
BASELINE: 105 passed in 2.69s
```
Sem esse baseline impresso, "0 failed" é indistinguível de "nada rodou". Já
caí nisso na ABSORPTION-03 — duas vezes, por `--timeout` sem `pytest-timeout` e
por word-split do zsh. Aqui o exit code e a contagem de coleta são conferidos
antes.

## As 10 mutações exigidas + 1
| # | DEFESA | MUTAÇÃO | EXPECTED_RED | OBSERVED_RED | exit | PASS |
|---|---|---|---|---|---|---|
| M1 | parser cron | aceita qualquer expressão | ≥1 | **28** | 1 | ✅ |
| M2 | timezone no cálculo | calcula em UTC | ≥1 | **1** | 1 | ✅ |
| M3 | timezone declarada | usa UTC do host | ≥1 | **8** | 1 | ✅ |
| M4 | reserva antes do efeito | `INSERT OR REPLACE` | ≥1 | **3** | 1 | ✅ |
| M5 | dedup persistente | reserva sempre concede | ≥1 | **3** | 1 | ✅ |
| M6 | autorização por ocorrência | ignora o autorizador | ≥1 | **3** | 1 | ✅ |
| M7 | shell implícito | aceita shell como argv[0] | ≥1 | **1** | 1 | ✅ |
| M8 | timeout de script | `timeout=None` | ≥1 | **1** | 1 | ✅ |
| M9 | failure event | suprime o alerta | ≥1 | **2** | 1 | ✅ |
| M10 | bypass do PDP no ticker | executa com credencial negada | ≥1 | **1** | 1 | ✅ |
| M11 | env allowlist | herda ambiente | ≥1 | **1** | 1 | ✅ |

**11/11 detectadas.** Todas revertidas após a medição.

Nota sobre M8: a rodada levou **32 s** contra ~2,7 s das outras. É a evidência
mais direta de que o timeout é real — sem ele, o teste `sleep(30)` roda até o
fim.

Nota sobre M2: só 1 teste vermelho, contra 8 da M3. A mutação M2 quebra a
janela de busca mas `_normalizar_local` ainda aplica o fuso no fim, então o
efeito é parcial. Registro como PASS (o critério é ≥1) e como cobertura mais
fina do que a M3, que é a mutação forte da mesma defesa.

## Baterias herdadas, revalidadas nesta missão
As 19 mutações da ABSORPTION-03 (filesystem, scheduler, registry race, timeout,
PDP por componente) continuam verdes sobre o código novo — nenhuma regressão.
