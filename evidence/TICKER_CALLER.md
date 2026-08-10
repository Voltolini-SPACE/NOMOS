# FASE 3 — CALLER REAL DO TICKER

`nomos scheduler rodar --raiz <dir> [--intervalo N] [--max-ticks N]`

O `Ticker` saiu de "classe testável sem chamador". O comando monta
explicitamente: store, clock, **autorizador**, runtime/PDP, alert sink e
handler de sinal para shutdown limpo.

## Foreground, não daemon
A missão proíbe instalar serviço. `rodar_ate()` roda em primeiro plano; SIGINT
e SIGTERM chamam `ticker.parar()`, que encerra a passada corrente e não começa
outra. Se o ambiente não permitir instalar handler (thread secundária), o
operador é **avisado** e orientado a usar `--max-ticks` — em vez de um
`except: pass` que deixaria Ctrl+C sem efeito e sem explicação.

## O autorizador continua obrigatório
`Ticker.__init__` recebe `autorizador` **posicional e obrigatório** desde a
correção da 04. O `AgendadorGovernado` sempre passa o seu; `SEM_AUTORIZACAO`
existe só para teste, e um teste estrutural garante que ele **não aparece** nem
em `cli.py` nem em `agendador.py`.

## Fluxo completo, provado na trilha
`test_ocorrencia_executada_pelo_ticker_com_traco_governado`: um job
`fs-escrever` executa e o arquivo aparece no disco com o conteúdo certo. A
trilha traz, em ordem:
```
pdp.decisao → pep.aplicacao → fs.escrever → scheduler.execucao.fim
```

**Nota honesta sobre `agente.ferramenta.usada`**: esse evento NÃO aparece, e
não deveria. Ele é do `AgentToolBoundary`, que governa as 8 ferramentas
NATIVAS. Para capacidade DINÂMICA (fs-*, sched-*, script-rodar) o papel de
fronteira é dividido entre o PDP (a capacidade está na autorização?), o PEP
(há ALLOW?) e `Adapter._coerente` (o pedido corresponde ao contexto
autorizado?). Meu teste original asseverava o evento errado; corrigi o teste,
não a expectativa — e registro a diferença em vez de escondê-la.

## Verificação por CLI real
```
$ nomos scheduler rodar --raiz <ws> --max-ticks 2 --intervalo 0.05
capacidades de agendamento: sched-apagar, sched-cancelar, sched-criar, …
armazém: <NOMOS_HOME>/scheduler/jobs.db
ticker em foreground (intervalo 0.05s) — Ctrl+C encerra.
ticks: 2 · ocorrências executadas: 0 · falhas: 0
```

## Gates
```
TICKER_PRODUCTION_CALLER = 1
TICKER_WITHOUT_AUTHORIZER = IMPOSSIBLE
TICKER_DIRECT_EXECUTOR_BYPASS = 0
```
