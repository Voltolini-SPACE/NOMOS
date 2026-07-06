# CONECTORES do loop — integrações externas

Filosofia NOMOS: o loop funciona 100% local. Conectores são opt-in e nunca
substituem o gate humano.

| Função | Ferramenta | Estado | Papel no loop |
|--------|-----------|--------|----------------|
| Branch + commit | git local | ✅ pronto | Única escrita que o loop faz fora dos arquivos |
| Push + PR | humano (GitHub Desktop / `git push` / `gh pr create`) | ✅ é o gate | Regra inviolável: push/publicação humanos |
| Abrir PR automático | GitHub MCP | ⏸️ desligado | Só se a regra for flexibilizada um dia; gate humano viraria o merge |
| Tarefas | loop/BACKLOG.md | ✅ pronto | Fonte única do "o que fazer"; Linear/Jira MCP só se necessário no futuro |
| Aviso de rodada | loop/LOOP_LOG.md | ✅ pronto | Notificação oficial (decisão 2026-07-06) |
| Aviso externo | Slack MCP / iMessage | ⏸️ desligado | Gancho: ao fim da etapa 7, enviar resumo da rodada. Ativar exige autorizar o conector no Cowork |

## Para ativar um conector depois
1. Autorizar o MCP no Cowork (Configurações → Conectores).
2. Adicionar a instrução correspondente na etapa 6 ou 7 do LOOP_PROMPT.md.
3. Registrar a mudança de política aqui e no CHANGELOG.
