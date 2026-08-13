# FASE 0 — FREEZE + REBASELINE · NOMOS-RUNTIME-ABSORPTION-01

Capturado no host canônico **PanheonAI.local** (usuário AI) em 2026-08-10T09:50:00Z,
ANTES de qualquer escrita. Reprodutível com os comandos indicados.

## Repositório canônico
`/Users/AI/Desktop/NOMOS_REPO/nomos` (NÃO em ~/Projects — exceção real, verificada)

```
HEAD    2cea197eb188121fcd507b53f02935b5edf435ad
branch  main
dirty   2 (apenas untracked: docs/architecture/NOMOS_MOSAIC_NAMING_*.md)
remote  origin https://github.com/Voltolini-SPACE/NOMOS.git
tags    v1.3.0rc20 (mais recente)
upstream 0 commits atrás de origin/main
index.lock  ausente        MERGE_HEAD  ausente
```

### Drift em relação à missão anterior
A missão FULL-ABSORPTION-01 baseou-se em `d55b4089`. Durante aquela janela, um
TERCEIRO fez merge do PR #7 (`fix/numeros-superficies`) às 02:48:07, levando a
main a `2cea197e`. Esta missão rebaselinou **no HEAD real do instante**, como
exigido — nenhum candidato foi construído sobre o SHA antigo.

## Worktrees no momento da captura
```
/Users/AI/Desktop/NOMOS_REPO/nomos                                  2cea197 [main]
/Users/AI/Projects/nomos-hermes-architecture/nomos-fix-wt           6c049c7 [fix/test-home-isolation-mc]
/Users/AI/Projects/nomos-hermes-capability-gap/workspace/nomos-nh-wt 13113f3 [feat/nh-capability-gap-01]
/Users/AI/Projects/nomos-hermes-capability-gap/workspace/nomos-num-wt 544ddee [fix/numeros-superficies]
```
Sujidade das irmãs: nomos-fix-wt=0, nomos-nh-wt=0, nomos-num-wt=1.

## Concorrência e colisão de alvo
- 10 processos `claude --output-format` vivos, todos com cwd `/Users/AI/Desktop`.
- `lsof +D /Users/AI/Desktop/NOMOS_REPO`: **nenhum arquivo aberto por terceiros**.
- Nenhuma worktree irmã escreve nos arquivos desta missão.

⇒ Existe concorrência no ecossistema, mas **não no alvo**. Regra aplicada: não
bloquear pela mera existência de sessões; bloquear só por colisão material.

## Superfície real revalidada (não assumida da missão anterior)
```
src/nomos/runtime/     sandbox.py, sandbox_s1.py   (nenhum daemon)
src/nomos/agents/      boundary.py, execucao.py, manifest.py, registry.py
src/nomos/orquestracao/ grafo, planejador, roteamento, recuperacao, registro
PDP dentro do NOMOS    AUSENTE (único hit era comentário em memory/store.py)
PEP/adapter            AUSENTE (hits de "adapter" eram mosaic/council, não relacionados)
callers de orquestracao em src/  ZERO
```

## Guards (intactos no início e no fim)
```
planner Hermes  2ecc5ff7051603675ccdf7ba087340759c246f26148a99b7db3be95628317ecc
WA antitamper   com.pantheon.openclaw.whatsapp-antitamper carregado
WhatsApp        enabled=False
toolchain Node  ~/.local/bin/node -> ~/.hermes/node/bin/node  (não remover ~/.hermes)
:9119 Hermes    1 listener   :18789 OpenClaw 2   :11434 Ollama 0 (fora)
```

## Worktree da missão
```
/Users/AI/Projects/nomos-runtime-absorption/wt
branch feat/nomos-runtime-absorption-01  (nascida de 2cea197e)
```

## Gate FASE 0
```
BASELINE_CURRENT=TRUE
ISOLATED_WORKTREE=TRUE
TARGET_COLLISION=FALSE
```
