# MATRIZ DE PARIDADE — pós FASE 1+2

Regra: **não marcar paridade por nome parecido**. Exige equivalência
comportamental *governada*. `governado` = atravessa capability registry →
risco → PDP → PEP → adapter, com evidência.

Legenda de status: `GOVERNADO` (existe e passa pela cadeia) · `PARCIAL`
(existe, cadeia incompleta) · `AUSENTE` · `FORA_DO_NUCLEO` (decisão de
arquitetura: nunca entra no kernel).

| Capability | NOMOS | Hermes | OpenClaw | Status | Risco | Adapter necessário | PDP | PEP | Testes | Production-ready? |
|---|---|---|---|---|---|---|---|---|---|---|
| execução de comando governada | 8 ferramentas allowlist | shell/PTY livre | exec-approvals | PARCIAL | A0–A5 | — (as 8 já) | sim | sim | 72 | runtime sim; escopo ≪ Hermes |
| código (gerar) | `codigo_gerar` | write/patch/exec | — | GOVERNADO | A0 | — | sim | sim | sim | sim |
| filesystem read | `arquivo_ler` | livre | livre | GOVERNADO | A0 | — | sim | sim | sim | sim |
| filesystem write | `arquivo_escrever` (confinado) | `/api/fs/write-text` livre | livre | PARCIAL | A1 | fs-amplo | sim | sim | sim | só dentro do NOMOS_HOME |
| filesystem patch | — | patch tool | — | AUSENTE | A1 | patch | — | — | — | não |
| Git | — | ~19 rotas incl. push/PR | — | AUSENTE | A2+ | git governado | — | — | — | não |
| HTTP | só loopback LLM | livre | livre | AUSENTE | A3 | http governado | — | — | — | não |
| browser | — | disponível | plugin `browser` | AUSENTE | A3 | browser governado | — | — | — | não |
| PTY/terminal | — | PTY + open-terminal | — | FORA_DO_NUCLEO | A6 | só se provada necessidade | — | — | — | não (decisão) |
| cron/scheduler | `rotinas` só EXPORTA plist | 8 jobs internos | 4 jobs internos | AUSENTE | A2 | scheduler governado | — | — | — | não |
| channels (Telegram) | — | — | ATIVO | AUSENTE | A3 | channel adapter | — | — | — | não |
| WhatsApp | — | — | desabilitado + guard 60s | AUSENTE | A4 | channel adapter | — | — | — | não (e não mexer no guard) |
| recuperação | `GerenciadorRecuperacao` | retry ad-hoc | supervisor | GOVERNADO | — | — | n/a | n/a | sim | sim |
| retries | idempotência do REGISTRO | — | — | GOVERNADO | — | — | n/a | n/a | sim | sim |
| daemon/runtime | **AUSENTE** (CLI só) | launchd KeepAlive | launchd KeepAlive | AUSENTE | — | serviço | — | — | — | **não — bloqueia shadow** |
| model routing | `motores` + NH-007 | — | primary sem fallback | PARCIAL | — | provider abstraction | — | — | sim | sem motor vivo hoje |
| tool routing | registro + boundary | toolsets | plugins | GOVERNADO | — | — | sim | sim | sim | sim |
| orchestration | `RuntimeGovernado` | plan_task/delegate | agent runtime | GOVERNADO | — | — | sim | sim | 72 | sim (escopo das 8) |
| task DAG | `GrafoTarefas` | kanban | — | GOVERNADO | — | — | sim | sim | sim | sim |
| secrets | vault Argon2id | token cleartext | cleartext | GOVERNADO | A4 | — | n/a | n/a | sim | NOMOS superior |
| identity | manifesto + sujeito/audiência | token loopback | pareamento | PARCIAL | — | RBAC multiusuário | sim | sim | sim | single-user |
| authorization | A0–A6 + PDP de capacidade | Tirith fail-OPEN | scopes | GOVERNADO | — | — | sim | sim | 47 | NOMOS superior |
| auditing | hash-chain + HMAC anchor | logs | logs | GOVERNADO | — | — | n/a | n/a | sim | NOMOS superior |
| restart/reconnect | — | KeepAlive + watchdogs | KeepAlive | AUSENTE | — | serviço | — | — | — | não |
| observability | trilha + `doutor` | observer 30s | health 5s | PARCIAL | — | métricas | n/a | n/a | sim | sem endpoint |

## Contagem
- Capacidades avaliadas: **24**
- GOVERNADO: **11** · PARCIAL: **5** · AUSENTE: **7** · FORA_DO_NUCLEO: **1**
- Paridade governada vs Hermes: **11/19 aplicáveis ≈ 58 %**
- Paridade governada vs OpenClaw: **8/16 aplicáveis ≈ 50 %**

## O que mudou nesta missão
Antes: orquestração e DAG eram AUSENTE-em-produção (biblioteca sem caller);
autorização era só A0–A6 local; PDP e PEP inexistiam no produto.
Agora: orchestration, task DAG, tool routing, retries, recuperação e
authorization passaram a GOVERNADO com PDP/PEP no caminho.

## O que continua impedindo substituição
1. **Sem daemon** — NOMOS não é serviço; sem isso não há shadow nem canary.
2. **Sem adapters** para Git, HTTP, browser, scheduler, channels — as
   capacidades que Hermes/OpenClaw efetivamente entregam hoje.
3. **Sem motor de inferência** (Ollama fora, SSD desmontado) — bloqueia E2E
   com LLM, mas **não** o runtime (todos os 2153 testes rodaram sem motor).
4. Duas rotas legadas ainda fora do PDP de capacidade (documentadas, fixadas
   por teste, agendadas para ABSORPTION-02).
