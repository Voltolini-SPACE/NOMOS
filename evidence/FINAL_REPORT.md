# NOMOS-RUNTIME-ABSORPTION-01 — RELATÓRIO FINAL

## STATUS_FINAL = PASS_RUNTIME_PDP_READY

```
BASELINE_HEAD=2cea197eb188121fcd507b53f02935b5edf435ad
MISSION_BRANCH=feat/nomos-runtime-absorption-01
MISSION_HEAD=ponta de feat/nomos-runtime-absorption-01 (o commit de docs;
              seu SHA não é gravável dentro dele mesmo — os 3 commits de
              código abaixo são estáveis e verificáveis)

ORCHESTRATION_REAL_CALLER=TRUE
PDP_IN_RUNTIME_PATH=TRUE
PEP_MANDATORY=TRUE
DIRECT_ROUTE_BYPASS=0 (caminho do runtime) / 2 rotas legadas boundary-only (documentadas)
ADVERSARIAL_SUITE=PASS (47/47, dentes verificados por mutação)
FULL_TEST_SUITE=PASS (2153 passed, 0 failed, 14 skipped, 2166 coletados)
LINT=PASS (ruff, src/ + tests/)
TYPECHECK=NOT_RUN (mypy não é dependência do projeto; skip é do baseline)
REGRESSION=0

HERMES_PARITY_PERCENT=58 (11/19 aplicáveis, governadas)
OPENCLAW_PARITY_PERCENT=50 (8/16 aplicáveis, governadas)

READY_FOR_ADAPTER_PHASE=TRUE
READY_FOR_SERVICE_INSTALL=FALSE   (não existe daemon; é trabalho da 02)
READY_FOR_SHADOW=FALSE            (depende de serviço + motor de inferência)
READY_FOR_CANARY=FALSE
READY_FOR_PRODUCTION_CUTOVER=FALSE
```

## Números exatos
| Métrica | Baseline | Final |
|---|---|---|
| testes coletados | 2095 | 2166 |
| passed | 2082 | 2153 |
| failed | 0 | **0** |
| skipped | 13 | 14 |
| ruff | limpo | limpo |

Os 14 skips são ambientais e pré-existentes (namespaces Linux, mypy/PyYAML fora
das dependências, SMTP frágil no macOS, Ollama). Nenhum foi introduzido aqui, e
nenhum teste foi enfraquecido, marcado xfail ou pulado para obter verde.

## Commits locais (nenhum push, merge, PR ou tag)
```
2bcfa5b feat(nomos): wire orchestration into governed runtime
829c5cf feat(nomos): enforce PDP on runtime execution path
a54af4a test(nomos): add adversarial authorization and bypass suite
<docs>  docs(nomos): record runtime absorption evidence
```

## Censo pós-implementação — as 12 perguntas

1. **Quantos callers reais usam `orquestracao`?** De **0 → 2** módulos de
   produção: `runtime/governado.py` e `cli.py` (`nomos orquestrar`).
2. **O runtime passa obrigatoriamente pelo PDP?** Sim. Comprovado pela ordem na
   trilha: `pdp.decisao` → `pep.aplicacao` → `agente.ferramenta.usada`.
3. **Existe caller mutante fora do PEP?** Sim, dois — `nomos agentes usar` e
   `simple/amigavel.py`. Ambos passam pelo boundary A0–A6 (não são bypass de
   política), mas não pelo PDP de capacidade. Fixados por censo estrutural.
4. **Existe path direto até o adapter?** Não a partir do runtime: o executor
   bruto vive na closure do PEP; `PontoDeAplicacao` tem `__slots__` e nenhum
   atributo devolve o callable.
5. **Existe bypass conhecido?** Nenhum no caminho do runtime. As duas rotas do
   item 3 são limitação declarada, não bypass silencioso.
6. **O NOMOS já executa efeitos reais governados?** Sim — DAG multi-nó com
   dependências executado de verdade, com DENY bloqueando dependentes.
7. **Que capacidades do Hermes ainda faltam?** Git, HTTP, browser, patch,
   scheduler, PTY (esta por decisão de arquitetura, não lacuna).
8. **Que capacidades do OpenClaw ainda faltam?** Channels (Telegram/WhatsApp),
   gateway HTTP+WS, pareamento de dispositivo, plugins, cron interno.
9. **Que adapters construir na próxima missão?** fs-amplo, git, http, browser,
   scheduler, channels, provider abstraction.
10. **O motor de inferência bloqueia só E2E ou o runtime?** **Só E2E.** Os 2153
    testes e as execuções reais rodaram com Ollama fora — orquestração governada
    não depende de LLM.
11. **NOMOS já pode ser instalado como serviço para shadow?** **Não.** Não há
    daemon: `runtime/` tem apenas sandbox; `rotinas` só exporta plist e nunca
    chama `launchctl`.
12. **O que ainda impede substituição completa?** Ausência de daemon, ausência
    dos adapters do item 9, motor de inferência fora, e as duas rotas legadas.

## Invariantes não negociáveis — todos verificados
```
DIRECT_ROUTE_BYPASS=FALSE (runtime)   PDP_OPTIONAL=FALSE      PEP_OPTIONAL=FALSE
DEFAULT_ALLOW=FALSE                   GENERIC_SUBPROCESS_IN_KERNEL=FALSE
UNCONTROLLED_SHELL=FALSE              UNCONTROLLED_PTY=FALSE
UNCONTROLLED_GIT=FALSE                UNCONTROLLED_HTTP_EXEC=FALSE
PLANNER_ASSIGNS_OWN_RISK=FALSE        RECOVERY_BYPASSES_DENY=FALSE
TESTS_WEAKENED_TO_PASS=FALSE
```
`PLANNER_ASSIGNS_OWN_RISK` era **TRUE** no baseline por um caminho não coberto
(grafo montado à mão) — corrigido nesta missão em três camadas.

## Produção intocada
```
PRODUCTION_MUTATED=FALSE
main NOMOS ainda em 2cea197e (nenhum commit, merge, push ou tag)
guard planner Hermes 2ecc5ff7…317ecc  intacto
:9119 Hermes vivo · :18789 OpenClaw vivo · WhatsApp enabled=False · antitamper carregado
~/.hermes intocado (toolchain Node depende dele)
LaunchAgents, hooks e infraestrutura produtiva: nenhuma alteração
```

## Próxima missão — NOMOS-RUNTIME-ABSORPTION-02 (NÃO executada)
Ordem sugerida, do mais barato/reversível ao mais caro:
1. Fechar as duas rotas legadas sob o PDP de capacidade.
2. Adapters governados: fs-amplo → git → http → scheduler → browser.
3. Provider abstraction + restaurar ≥1 motor (remontar SSD `MODELS_LOCAL`).
4. Instalar NOMOS como serviço (daemon + healthcheck + restart).
5. Shadow contra Hermes/OpenClaw → adversarial E2E → canary → restart/recovery
   → cutover reversível.

Hermes e OpenClaw permanecem ativos e obrigatórios durante toda a 02.
