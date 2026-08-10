# FASE 12 — MUTATION EVIDENCE

## Harness verificado ANTES de confiar
```
PYTEST_VERSION=pytest 9.1.1
SELECTED=test_absorption05_callers.py test_absorption04_ticker_script.py
         test_absorption03_scheduler.py
COLLECTED=117
EXIT_CODE=0
BASELINE=117 passed
```

## As 10 mutações exigidas + 1
| # | DEFESA | MUTAÇÃO | OBSERVED_RED | exit | PASS |
|---|---|---|---|---|---|
| M1 | caller de `registrar_scheduler` | remove a chamada | 1 | 1 | ✅ |
| M2 | autorizador obrigatório | aceita `None` | 2 | 1 | ✅ |
| M3 | execução sem credencial | desvia direto ao executor | 1 | 1 | ✅ |
| M4 | validação da allowlist | remove `validar_executaveis` | 1 | 1 | ✅ |
| M5 | allowlist de binário | permite qualquer | 4 | 1 | ✅ |
| M6 | escopo de cwd do script | `cwd` livre | 2 | 1 | ✅ |
| M7 | registry version | ignora `versoes` | **3** | 1 | ✅ |
| M8 | audit do agendador | suprime | 1 | 1 | ✅ |
| M9 | failure event | suprime alerta | 1 | 1 | ✅ |
| M10 | cron corrompido | volta a virar `None` | 2 | 1 | ✅ |
| M11 | revalidação de capacidade sumida | ignora | 1 | 1 | ✅ |

**11/11 detectadas.** Todas revertidas (ruff limpo depois).

## Dois falsos resultados que eu tratei como inválidos, não como PASS

**M7 deu "0 failed" na primeira tentativa.** Não era a defesa — era a
**seleção**: os testes de registry race vivem em
`test_absorption03_race_timeout.py`, que eu não tinha incluído no seletor.
Refeito com a suíte correta (COLLECTED=78, BASELINE=78), a mutação derruba 3
testes. Verde por seleção errada é falso verde, e a missão manda não aceitá-lo.

**M8 e M10 deram `exit=2` com "errors".** Minhas mutações quebraram a sintaxe —
erro de coleta não é vermelho válido. Refeitas com mutações sintaticamente
corretas (guard trocado em vez de meia-linha), ambas derrubam testes de
verdade: M8 → 1, M10 → 2.

Ambos os casos entram aqui porque são exatamente o tipo de resultado que, aceito
sem olhar, produz um relatório dizendo "todas as defesas verificadas" quando
metade nem rodou.
