# LOOP_PROMPT — protocolo de uma rodada do loop NOMOS

> Disparo manual: peça ao Claude (Cowork ou Claude Code, com a pasta do repo
> aberta): **"Execute uma rodada do loop NOMOS conforme loop/LOOP_PROMPT.md"**.
> Agendamento futuro: usar este mesmo texto como prompt da tarefa agendada.

## Sequência obrigatória (nesta ordem, sem pular etapas)

### 0 · Trava anti-concorrência
- Se `loop/.lock` existir com menos de 6 h: **abortar** e registrar
  `RODADA ABORTADA (lock ativo)` no LOOP_LOG. Se mais velho: considerar órfão, remover.
- Criar `loop/.lock` com timestamp UTC e descrição da rodada.

### 1 · Carregar contexto
- Ler `CLAUDE.md`, o bloco **ESTADO ATUAL** de `loop/LOOP_LOG.md` e `loop/BACKLOG.md`.
- Conferir `git status`: se a árvore não estiver limpa, **abortar** e registrar
  (nunca trabalhar por cima de mudanças humanas não commitadas).

### 2 · Escolher missão (exatamente 1 por rodada)
- Pegar a primeira missão com status `pronta` no BACKLOG (ordem = prioridade).
- Se não houver: registrar `RODADA VAZIA — backlog sem missão pronta` e encerrar (etapa 7).
- Marcar a missão como `em curso` no BACKLOG.

### 3 · Branch
- A partir da `main`: `git checkout -b loop/<ID>-<slug-curto>`.

### 4 · Executar (sub-agente `nomos-executor`)
- Implementa a missão pelo método loop-100: código + testes + CHANGELOG.
- Escopo estrito: só o que a missão pede. Dúvida estrutural = parar e registrar
  como `bloqueada` com a pergunta para o humano.

### 5 · Revisar (sub-agente `nomos-revisor` — independente)
- Roda `python -m pytest -q` e `ruff check .`; confere o checklist de governança.
- Veredito: **PASS** ou **FAIL (motivos)**. O executor nunca se auto-aprova.

### 6 · Fechar a missão
- **PASS** → commit na branch (mensagem convencional + trailer
  `Loop-Rodada: <N>`); missão vira `feita — aguardando push humano` no BACKLOG.
- **FAIL** → 1 tentativa de correção (executor) + re-revisão. Persistindo:
  `git restore .` na branch, missão vira `bloqueada` com os motivos no LOOP_LOG.

### 7 · Registrar e encerrar (sempre, mesmo em aborto)
- Nova entrada no topo das RODADAS do `loop/LOOP_LOG.md` (usar o modelo) e
  atualizar o bloco ESTADO ATUAL (inclusive a sugestão de próxima ação).
- O registro no LOOP_LOG é a notificação oficial da rodada.
- Remover `loop/.lock`. **Parar.**

## Proibições absolutas da rodada
`git push` · abrir PR · merge · tag · commitar na `main` · mais de 1 missão ·
tocar em `~/`, credenciais ou qualquer coisa fora do repo · continuar com
testes quebrando · remover a trava de outra rodada ativa (< 6 h).

## Gate humano (fora do loop)
Humano revisa a branch → push → PR → merge. O loop só prepara.
