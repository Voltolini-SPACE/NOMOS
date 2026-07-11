# MC35 — `nomos loop`: trabalho contínuo governado (SPEC, proposto)

**Data:** 2026-07-06 · **Status:** proposto (spec-only, nenhum código nesta missão)
**Missão de origem:** decisão do operador — "o sistema de loop deve existir
dentro do NOMOS, para todos os usuários" (2026-07-06).
**Parentes:** ROADMAP_4 Trilha P (P1 — executor de missões multi-passo);
`loop/` na raiz do repo (protótipo interno que validou o desenho).

## 1. Tese
O usuário tem projetos e tarefas que avançam em rodadas pequenas e auditáveis.
Hoje o NOMOS responde; com `nomos loop` ele **trabalha em ciclos**: pega a
próxima missão de uma fila, planeja, pede aprovação, executa, um par revisor
confere, registra evidência e para. O usuário volta e encontra progresso — com
a governança de sempre (A0–A6, fail-closed, aprovação humana, zero surpresa).

## 2. As 5 peças → módulos existentes (nada de infra nova)
| Peça do loop | Implementação no NOMOS |
|---|---|
| 1 · Disparo agendado | `simple/rotinas.py` (`devidas()`, policy + approver já embutidos) |
| 2 · Contexto do projeto | `loop/PROJETO.md` na pasta do projeto do usuário |
| 3 · Continuidade entre rodadas | `loop/LOOP_LOG.md` (bloco ESTADO ATUAL + diário) |
| 4 · Ações externas | skills governadas + MCP client existente — sempre atrás de gate; **push/publicação seguem humanos** |
| 5 · Escreve ≠ confere | executor = motor via roteador; revisor = passada independente via `council/orchestrator` (trace auditável) |

Peças que o protótipo provou serem obrigatórias: fila (`BACKLOG.md`), trava
anti-concorrência (`loop/.lock`), aborto com árvore suja, 1 missão por rodada.

## 3. UX (CLI, pt-BR, no padrão dos comandos atuais)
- `nomos loop iniciar [pasta]` — cria `loop/` (PROJETO, BACKLOG, LOOP_LOG) com
  assistente amigável; explica as regras em linguagem de iniciante.
- `nomos loop status` — ESTADO ATUAL + próxima missão + pendências do humano.
- `nomos loop rodada` — executa UMA rodada (protocolo §4). `--dry-run` mostra
  o plano e para (padrão na 1ª execução).
- `nomos loop backlog` — listar/adicionar/reordenar missões.
- `nomos loop agendar "07:00"` — açúcar sobre `rotinas criar` com ação
  `loop.rodada`.

## 4. Protocolo da rodada (portado do protótipo `loop/LOOP_PROMPT.md`)
0. Trava (`loop/.lock`; < 6 h = abortar) → 1. contexto + árvore limpa (git
   sujo = abortar; pasta sem git: verificação de mtime/manifesto) →
2. escolher 1ª missão `pronta` → 3. isolar (branch `loop/<id>` se git; senão
   cópia de trabalho) → 4. executor implementa (PLANO → gate de consentimento
   conforme nível A da ação → execução passo a passo) → 5. revisor independente
   (checklist + veredito PASS/FAIL; nunca o mesmo contexto do executor) →
6. PASS: commit local / FAIL: 1 correção, senão reverter e `bloqueada` →
7. registrar rodada no LOOP_LOG + `AuditLog` (HMAC), remover trava, **parar**.
Proibições: push, publicar, merge, >1 missão, sair da pasta do projeto,
continuar com verificação falhando.

## 5. Missões de implementação (1 rodada cada — fila em `loop/BACKLOG.md`)
| ID | Entrega | Critério de aceite (testável) |
|----|---------|-------------------------------|
| LP1 | Modelo de dados + `nomos loop iniciar` | cria os 3 arquivos com templates; idempotente; testes de scaffold |
| LP2 | `nomos loop status` | lê ESTADO/BACKLOG reais; saída amigável; erro claro se não iniciado |
| LP3 | Rodada `--dry-run` | escolhe missão, monta PLANO legível (passos + nível A + arquivos afetados), NADA executa; trava e aborto por árvore suja funcionando |
| LP4 | Execução gateada | integra `ConsentRegistry` (aprovação por rodada) + `AuditLog` (evidência HMAC por rodada); fail-closed em CI/script |
| LP5 | Revisor independente | passada via `council/orchestrator` com trace; FAIL bloqueia commit; teste com falha injetada |
| LP6 | Agendamento + site | `loop agendar` via rotinas; docs de usuário; site atualizado (REGRA MC33) |
| LP7 | Aviso de fim de rodada | Registro no LOOP_LOG sempre; aviso externo (desktop/conector MCP) opt-in atrás de gate; nunca bloqueia a rodada se o aviso falhar |
| LP8 | `nomos loop entregar` | Pacote de entrega da rodada: diff, evidências (audit), texto de commit/PR sugerido e instruções passo a passo para o push HUMANO; nada é enviado pelo agente |

## 6. Fora de escopo (MC35)
Push/PR automáticos · execução paralela de missões · loop em pastas do sistema
(`~/`, raiz) · qualquer telemetria · UI no painel (fica para MC futuro).

## 7. REGRA MC35 — dogfooding vira produto (decisão do operador, 2026-07-06)
Toda ferramenta interna criada para desenvolver o NOMOS, uma vez validada em
uso real, DEVE virar missão de produto para todos os usuários — nunca ficar
só como ferramenta interna. Mapeamento atual: protocolo do loop → LP3/LP4 ·
contexto de projeto (CLAUDE.md interno) → `loop/PROJETO.md` (LP1) · diário/
estado → LOOP_LOG (LP1/LP2) · executor+revisor (.claude/agents) → LP5 ·
conectores/avisos (CONECTORES.md) → LP7 · gate de push humano → LP8.
Ferramentas internas futuras nascem já com a pergunta: "qual é a versão disso
para o usuário?" — registrada na spec da missão correspondente.

## 8. Riscos
- Rodada travar no meio → trava com timestamp + rodada seguinte detecta órfã.
- Usuário iniciante não entender git → modo sem git (manifesto de arquivos) é
  degradação explícita, com aviso.
- Motor local fraco para missões grandes → regra da fila: missão que não cabe
  numa rodada volta como `bloqueada` pedindo quebra ao humano.
