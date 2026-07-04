# NOMOS v1.2.0rc1 — Delivery Ready

## Status
STATUS_FINAL=PASS (local + CI remoto verde nos 3 SOs; tag criada)
CI_RUN=28706064138 (d465f08) · CONCLUSION=success · 17/17 jobs
TAG=v1.2.0rc1-delivery-ready (aponta para d465f08)

## Resumo
Esta entrega fecha as fases F1–F6 do plano de validação crítica, com histórico
local, agentes governados, endurecimento anti-injection, UX/memória tipada,
rotinas dry-run e smoke pós-install. Parte de v1.2.0rc1 (remoto e3c4ca9) e
leva o código a v1.3.0rc4.

## Commits
| Commit | Fase | Entrega |
|---|---|---|
| 8d4bb44 | F1 | anti prompt-injection (P0), .coverage fora do git, docs 27→25, mypy CI, XSS |
| 455b41b | F2 | histórico de conversas (local, cifrável, modo privado, retenção) |
| 0b29e57 | F3 | agentes locais governados (agente não é bypass do gate) |
| 19f1bf7 | F4 | UX: memória tipada, candidatas, erro humano, modo iniciante |
| 240362a | F5+F6 | rotina dry-run + smoke CI + fix empacotamento dos agentes |
| 129d309 | SHIM_OPERACIONAL | `__main__.py` p/ `python -m nomos` (FEATURE_NOVA=NAO, RISCO=BAIXO) |
| 88b6275+ | DOCS | release notes delivery-ready |

## Garantias preservadas (provadas por teste)
- Local-first — cadeado ligado por padrão; egress negado na política.
- Fail-closed — sem TTY/aprovação, sensível é negado (rc=3).
- Zero telemetria — `test_egress_zero`.
- Sem cloud silenciosa — nuvem só com cadeado aberto + chave + A2+A3.
- Sem bypass de aprovação — nenhum caminho novo de autorização.
- Sem rotina sensível automática — skill que pede aprovação não roda sozinha.
- Sem persistência em modo privado — store `:memory:`, FS inspecionado.
- Sem agente como bypass do gate — manifesto fechado, mesmo gate A0–A6,
  sem herança de permissão.
- Tag somente com CI verde.

## Testes locais (evidência da promoção)
- Total de testes: **494 passed**
- Coverage: **84% geral** (kernel: policy/localidade 100%, vault 97%)
- RUFF: PASS (All checks passed!)
- Build: PASS (nomos-1.3.0rc4-py3-none-any.whl)
- Smoke wheel (venv limpo): PASS
- `nomos doutor`: PASS (rc=0)
- `python -m nomos doutor`: PASS (rc=0, via shim)
- `nomos agentes listar`: PASS (3 oficiais: pesquisador-local A0,
  programador A1, seguranca A0)
- `git fsck --full`: PASS · árvore: CLEAN

## CI remoto
- Status: **PASS** — run 28706064138, conclusion=success, **17/17 jobs**.
- Jobs: testes em ubuntu/macos/windows × py3.10–3.13; cobertura (informativa);
  mypy (informativo); smoke pós-install (wheel + doutor) nos 3 SOs.
- Link: https://github.com/Voltolini-SPACE/NOMOS/actions/runs/28706064138

### Correções de CI aplicadas nesta promoção (commits separados)
O CI estava vermelho no Windows **desde antes** desta entrega (o base
e3c4ca9 já falhava). Diagnóstico e correção sem mascarar:
- **1.3.0rc5 (46d07c7)** — fins-de-linha: 35 falhas "checksum divergente"
  no Windows. `.gitattributes` força LF; SDK e testes gravam LF determinístico.
  35 → 1.
- **1.3.0rc6 (d465f08)** — gate POSIX: `test_lockout_arquivo_0600` verificava
  modo `0600` (inaplicável no Windows); recebeu o `skipif(nt)` padrão. 1 → 0.

## Correções críticas
- **Anti prompt-injection (F1)**: conteúdo recuperado (RAG/memória) é
  envelopado como DADO com marcador aleatório; a intenção de skill considera
  apenas o texto digitado. Nota hostil na memória não dispara skill (teste).
- **Modo privado sem persistência (F2)**: conversa privada roda em SQLite
  `:memory:`; teste inspeciona o filesystem e prova que nada é gravado.
- **Agentes incluídos no wheel (F6)**: manifestos oficiais estavam em
  `examples/` e não iam no wheel — pego pelo smoke, movidos para
  `src/nomos/agents/oficiais/` + package-data, reconfirmado em venv limpo.
- **Shim `python -m nomos`**: adicionado `__main__.py` (4 linhas) que delega
  ao mesmo `cli.main`. TIPO=SHIM_OPERACIONAL, FEATURE_NOVA=NAO, RISCO=BAIXO.

## Riscos remanescentes
1. CI verde no GitHub: verificação depende do push desta promoção.
2. Auditoria de segurança independente do kernel: não realizada.
3. Publicação (release GitHub/PyPI): pendente.
4. mypy informativo (não bloqueante), escopo kernel.

## Backlog pós-delivery — NOMOS Motor Council
**Status:** Validado como conceito.
**Implementação:** Não iniciada nesta missão.
**Motivo:** Promoção controlada não permite features novas.
**Prioridade sugerida:** P2 após delivery-ready, CI verde e tag criada.

### Conceito
Criar um Conselho de Motores onde múltiplos motores geram respostas
independentes, julgam respostas anonimizadas de forma cega, classificam riscos
e um árbitro monta a resposta final antes do envio ao usuário.

### Pipeline previsto
1. Classificar risco da solicitação.
2. Decidir se o conselho é necessário.
3. Gerar respostas independentes.
4. Anonimizar e embaralhar respostas.
5. Juízes avaliam por rubrica estruturada.
6. Árbitro monta resposta final.
7. Policy Gate valida antes do envio.
8. Log local redigido é gravado.
9. Em modo privado, não persistir julgamento.

### Regras obrigatórias futuras
- Não usar nuvem se o cadeado local estiver ativo.
- Não enviar dados sensíveis para motor cloud.
- Não permitir que motor ou agente burle o gate.
- Juiz não julga a própria resposta quando houver motores suficientes.
- Se a divergência for alta, não fingir certeza.
- Se qualquer juiz apontar risco alto, escalar para gate final.
- Se o gate reprovar, bloquear resposta.
- Logs redigem segredos.
- Modo privado não persiste julgamento.
- Conselho não executa ação sensível sem aprovação humana.

### Comandos futuros propostos
```bash
nomos conselho status
nomos conselho on
nomos conselho off
nomos conselho testar "texto"
nomos conselho modo rapido
nomos conselho modo balanceado
nomos conselho modo critico
nomos conselho modo paranoico
```

### Testes futuros obrigatórios
Respostas anonimizadas antes do julgamento; motor não julga a própria resposta
quando possível; cloud bloqueada com cadeado ativo; dados sensíveis forçam modo
local; modo privado não persiste julgamento; divergência alta gera ressalva;
alerta de segurança bloqueia ou escala; resposta final passa pelo Policy Gate;
logs redigem segredos; caminho rápido não chama conselho desnecessariamente;
conselho crítico usa múltiplos motores; fallback com um motor local só.

## Próximo passo recomendado (apenas 1)
Verificar o CI da promoção e, com ele verde, criar a tag
`v1.2.0rc1-delivery-ready` — depois disso, auditoria independente do kernel.
