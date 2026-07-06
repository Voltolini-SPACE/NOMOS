# NOMOS — Roadmap 3: Aprimoramentos, Funcionalidades e Conexões

**Base:** v1.3.0rc17 (`b58b066`) · **Data:** 2026-07-05 · **Status:** proposto
**Antecessores:** `ROADMAP.md` (v0.12→v1.0, executado) · `ROADMAP_2.md` (v1.0→v1.5)
**Missão de origem:** MC30 — plano de melhorias, funcionalidades e conexões.

> Regra de ouro herdada: cada item nasce **atrás do gate** (A0–A6), local-first,
> fail-closed, com teste e evidência. Conexão nova nenhuma liga sozinha: toda
> saída da máquina é opt-in explícito com aprovação humana. Push/publicação
> continuam decisão humana. Nada aqui é promessa de marketing — é backlog de
> engenharia com critério de pronto.

---

## 0. Onde estamos (inventário real da rc17)

- **Motores (14 no catálogo):** cérebro embutido, Ollama (texto/coder/visão),
  Claude nuvem (opt-in), SD WebUI, ComfyUI, Piper (TTS), Whisper (STT),
  memória-local SQLite, busca FTS5, skills, roteador — `cognition/engine_catalog.py`.
- **Cognição:** roteador explicável com trace (MC29), arbitragem REAL multi-motor
  local-first com nuvem gateada, pipelines, RAG/semântica, memória com
  candidatas/contradições, feedback local do usuário, prompt_guard.
- **Governança:** SECURITY_POLICY SEC-01…12 executável, council dry-run travado,
  10 flags proibidas, vault Argon2id, auditoria com hash + âncora HMAC,
  evidências auditáveis (`nomos evidencia`), update agent (docs+marca) e git
  agent read-only como gates de CI.
- **Superfícies:** CLI pt-BR, chat, painel loopback read-only (política viva +
  evidências), painel de aprovações, site estático com brandbook congelado.
- **Distribuição:** wheel/sdist, instaladores 1-clique, CI 3 SOs × py3.10–3.13,
  release gateada; `packaging/homebrew` e `packaging/winget` como esqueletos;
  `tools/make_sbom.py` existente.

## 1. Formato dos itens

Cada item tem: **Objetivo · Base real (arquivo/embrião) · Risco · Pronto quando**.
Executar um item = abrir missão loop-100 própria (spec → teste → evidência →
commit). IDs estáveis para referência (A=aprimorar, B=funcionalidade,
C=conexão, D=distribuição).

---

## Onda A — Aprimoramentos imediatos (risco baixo, 1 missão cada)

**A1 · Update agent propõe correção de marca (não só detecta)**
Objetivo: `--diff` gera proposta textual para cada `brand:*` reprovado.
Base: `tools/nomos_update_agent.py` (checks MC29 prontos; `run_diff` só cobre links).
Risco: baixo (proposal-only). Pronto quando: cada check de marca reprovado gera
patch proposto correspondente, com teste positivo/negativo.

**A2 · `nomos evidencia listar` + anexo automático de teste**
Objetivo: listar pacotes com status de integridade; `--com-pytest` roda a suíte
e anexa o resultado ao pacote.
Base: `kernel/evidencia.py` (verificar_pacote pronto). Risco: baixo.
Pronto quando: listar mostra íntegro/violado por pacote; pacote com saída real
do pytest vira evidência de missão padrão.

**A3 · Doutor unificado (um check-up só)**
Objetivo: `nomos doutor` incorpora update agent (docs/marca) e git agent
(quando rodando de um repo) como seções do check-up.
Base: `simple/doutor.py` + os dois agentes MC29. Risco: baixo.
Pronto quando: doutor mostra as 3 famílias com próximo passo único.

**A4 · Painel: auto-refresh + catálogo de capacidades**
Objetivo: meta-refresh opcional (`?refresh=10`, sem JS externo) e seção
"Capacidades" (dados do `skill_catalogo`).
Base: `interface/painel_web.py`, `ext/skill_catalogo.py`. Risco: baixo.
Pronto quando: painel exibe catálogo e se atualiza sozinho quando pedido,
seguindo loopback/read-only (testes de 405/404 intactos).

**A5 · Cobertura como gate dirigido**
Objetivo: job de cobertura passa a exigir ≥90% nos módulos novos
(`kernel/evidencia`, `tools/nomos_*_agent`, `ext/skill_catalogo`).
Base: `.github/workflows/ci.yml` (job cobertura já roda `--cov-fail-under=80`).
Risco: baixo. Pronto quando: CI falha se módulo novo regredir cobertura.

**A6 · Catálogo de erros amigáveis**
Objetivo: toda exceção de superfície vira mensagem "o que houve · como resolver
· comando", com código de erro estável (NOMOS-Exxx).
Base: `simple/erros.py`. Risco: baixo.
Pronto quando: top-20 erros mapeados com teste de mensagem; nenhum traceback
cru em fluxo normal de CLI/chat.

## Onda B — Funcionalidades de produto

**B1 · Conversa de verdade: streaming + memória no contexto** *(ROADMAP_2 v1.1)*
Objetivo: resposta em streaming (Ollama/embutido) e memórias relevantes
injetadas no prompt com transparência via `/contexto`.
Base: `cognition/router.py`, `memory.buscar`, `providers.py`. Risco: médio
(latência/UX). Pronto quando: primeira palavra <2 s com Ollama; `/contexto`
lista as memórias usadas; testes com provider fake de streaming.

**B2 · `/arbitrar` no chat**
Objetivo: a arbitragem real (MC29) disponível na conversa, com as mesmas
barreiras da CLI (nuvem só com opt-in interativo).
Base: `cognition/arbitragem.py`, `council/chat_dry_run.py` como molde de UX.
Risco: médio. Pronto quando: `/arbitrar pergunta` responde com motor vencedor +
confiança; sem motor pronto ⇒ mensagem honesta; testes de contrato espelhando
os 25 da CLI.

**B3 · Multi-agente executável (personas oficiais)**
Objetivo: pesquisador-local, programador e segurança viram personas roteáveis
(`nomos agente usar <nome>`), com handoff registrado em evidência.
Base: `agents/{registry,manifest,boundary}.py` + 3 JSONs oficiais.
Risco: médio. Pronto quando: cada persona restringe permissões pelo manifesto
(boundary testado) e o handoff gera pacote de evidência.

**B4 · Voz ponta a ponta local**
Objetivo: `nomos ouvir` (Whisper → texto → resposta) e `nomos falar` (Piper),
100% local.
Base: `cognition/arquivos.py` (whisper), `criacao.py` (piper) — binários já
integrados. Risco: médio (dependências externas). Pronto quando: fluxo completo
funciona com os binários presentes e degrada com instrução clara sem eles.

**B5 · Memória 2.0: revisão visível + embeddings opcionais**
Objetivo: fila de candidatas aparece no painel (aprovar/rejeitar continua no
terminal); busca semântica opcional com embedding local pequeno.
Base: `memory.py` (candidatas/contradições prontos), `rag.py`, extra `cerebro`.
Risco: médio. Pronto quando: painel lista candidatas; `nomos memoria revisar`
zera a fila; embeddings só com modelo local presente (nunca nuvem por padrão).

**B6 · Skills por intenção na conversa** *(ROADMAP_2 v1.2)*
Objetivo: frase do usuário casa com keyword do manifesto ⇒ NOMOS **propõe** a
skill ("posso rodar busca-arquivos? [s/n]") e roda só com confirmação.
Base: `ext/skill_intencao.py` (embrião existente!), manifestos com `keywords`.
Risco: médio (nunca rodar sem confirmar — teste). Pronto quando: proposta
aparece, negação não executa, execução passa pelo gate de sempre.

**B7 · Rotinas com gatilho de sistema (opt-in)**
Objetivo: `nomos rotinas exportar` gera launchd plist / systemd user timer /
Task Scheduler XML — o usuário instala; NOMOS nunca instala sozinho.
Base: `simple/rotinas.py`, `kernel/plataforma.py`. Risco: baixo-médio.
Pronto quando: arquivo gerado validado por teste em cada SO (golden files) e
doc de instalação manual.

## Onda C — Conexões (todas atrás de gate; nada liga por padrão)

| ID | Conexão | Nível | O que sai da máquina | Estado |
|---|---|---|---|---|
| C1 | **MCP server local** — NOMOS expõe skills/memória/evidências como tools (Model Context Protocol) p/ Claude Desktop e afins | A0/A1 (loopback) | nada (cliente é local) | proposto |
| C2 | **MCP client** — NOMOS consome servers MCP locais como "skills externas" com manifesto de risco | A5 por tool | nada por padrão | proposto |
| C3 | **Motores OpenAI-compatíveis** (LM Studio, llama.cpp server, LocalAI) | A0 (loopback) | nada | proposto |
| C4 | **Telegram bridge** — briefing/rotinas viram mensagem; comandos com allowlist | A2+A3 | só o que a rotina aprovada enviar | proposto |
| C5 | **E-mail (IMAP/SMTP)** — resumo diário local da caixa; envio só com aprovação por mensagem | A2+A3 | credencial no vault; corpo só local | proposto |
| C6 | **Calendário CalDAV (read-only)** — agenda no briefing | A2+A3 | nada além do fetch | proposto |
| C7 | **Pasta viva** — watcher local ingere documentos p/ memória com aprovação por arquivo | A0/A1 | nada | proposto |
| C8 | **Webhooks locais de entrada** — painel recebe POST loopback com token p/ integrações caseiras | A0 (loopback) | nada | proposto |

Diretrizes C: cada conector é um módulo isolado com manifesto (o que lê, o que
envia, nível A, como revogar), aparece no catálogo de capacidades com risco
visível, e ganha teste de contrato com dublê de rede (nunca rede real no CI).
**C1 é a alavanca estratégica:** conecta o NOMOS ao ecossistema de agentes sem
trair o local-first — o servidor MCP escuta só em loopback e cada tool call
sensível passa pelo gate/painel de aprovações.

## Onda D — Plataforma e distribuição

**D1 · Nome próprio no PyPI** — resolver de vez a colisão: publicar como
`nomos-agent` (ou similar), atualizar manual/site/update-agent check; `pip
install nomos-agent` vira caminho oficial. Pronto quando: release no PyPI +
docs coerentes + check de marca ajustado.

**D2 · Homebrew tap + winget reais** — `packaging/{homebrew,winget}` saem de
esqueleto para fórmula/manifest publicáveis com SHA das releases. Pronto
quando: `brew install se7enpay/nomos/nomos` e `winget install nomos` documentados
e testados em CI de release.

**D3 · Atualização proposta-e-assinada** — `nomos atualizar` valida assinatura
ed25519 do release (base: `ext/signing.py`, trust store) e **propõe**; aplicar
continua humano. Pronto quando: release não-assinada é recusada em teste.

**D4 · SBOM + atestado na release** — `tools/make_sbom.py` entra no workflow de
release; SBOM anexado aos assets. Pronto quando: release publica SBOM e o
manual de segurança referencia.

**D5 · Marketplace de skills assinadas (opt-in)** — catálogo remoto opcional
consumido via trust store; instalação continua manifesto+checksum+assinatura+
aprovação. Pronto quando: skill de exemplo instala do catálogo remoto de teste
com toda a cadeia verificada.

**D6 · Site: seção Conexões + docs geradas** — landing ganha seção honesta de
conectores (estado real: proposto/beta/pronto), sincronizada pelo update agent.

---

## Top-10 priorizado (ordem recomendada)

| # | Item | Por quê primeiro |
|---|---|---|
| 1 | B1 streaming+memória | é o que o usuário sente no primeiro minuto |
| 2 | A6 erros amigáveis | corta o custo de suporte de tudo que vem depois |
| 3 | B6 skills por intenção | transforma skills de recurso em produto |
| 4 | C1 MCP server | maior alavanca de ecossistema com risco controlado |
| 5 | C3 motores OpenAI-compat | multiplica motores locais sem custo de manutenção |
| 6 | A1 diff de marca | fecha o ciclo detectar→propor do guardião |
| 7 | B5 memória 2.0 | diferencial "agente que lembra" com governança |
| 8 | D1 PyPI nome próprio | remove a maior fricção de instalação que restou |
| 9 | B2 /arbitrar no chat | leva o melhor motor cognitivo à superfície principal |
| 10 | B4 voz ponta a ponta | demo perfeita do local-first (nada sai, e fala) |

Dependências fortes: B6→A6 (erros claros nas propostas); C4/C5/C6→A6+B7;
D5→D3 (assinatura); B2→B1 (UX de chat estável). Quick wins de fim de semana:
A2, A3, A4.

## Anti-metas (o que este plano conscientemente NÃO fará)

Telemetria/analytics (zero, sempre); nuvem como default em qualquer fluxo;
conector que liga sem opt-in; execução de skill sem confirmação; navegador
automatizado (superfície de risco desproporcional por ora); reescrita de
arquitetura ("big-bang") — tudo aqui é evolução dos módulos existentes.

## Como abrir cada missão

```text
MISSÃO: <ID> — <nome do item>
USAR SKILL: implementation-loop-100
CONTEXTO: NOMOS rc17+, item <ID> do docs/ROADMAP_3.md
ESCOPO: (Objetivo/Base real do item) · FORA: push, telemetria, defaults de nuvem
CRITÉRIOS: "Pronto quando" do item + suíte verde + ruff + gates dos agentes
ENTREGA: commit(s) + testes + evidência (nomos evidencia criar) + changelog
```
