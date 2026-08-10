# FASE 7 — FILESYSTEM REVALIDATION (independente)

**0 FULL / 8 PARTIAL / 1 MISSING / 2 FORA_DO_NUCLEO · 5 críticas em gap.**

Os três motivos que a ABSORPTION-03 registrou foram verificados um a um pelo
censo desta missão:

| Motivo da 03 | Estado verificado agora |
|---|---|
| (A) sem caller de produção | **CORRIGIDO** — `cli.py` expõe `--adapters` e `--raiz` |
| (B) `wiring.py` untracked | **CORRIGIDO** — commitado; worktree limpa |
| (C) confinamento opt-in default aberto | **CORRIGIDO** — mutante exige raízes, fail-closed |

E as correções de segurança finais da 03 também:
- `decisor.py` confina por **componente** (`realpath`+`commonpath`) —
  `/ws/../etc/passwd` não passa;
- `fs-listar` com padrão absoluto devolve erro **tipado**;
- `fs-criar-dir` tem teste.

## Por que ainda não é FULL
O critério de FULL tem 7 itens. O que falta agora não é mais (A), (B) nem (C) —
é **equivalência comportamental** em capacidades específicas:
- `FS-READ-BINARY` MISSING: `fs-ler` recusa binário explicitamente (honesto),
  mas não há equivalente ao `/api/fs/read-data-url` do Hermes;
- `fs-editar` não tem patch unificado/multi-arquivo nem diff auditável;
- as nativas `arquivo_ler`/`arquivo_resumir` seguem sem resolver próprio,
  protegidas apenas quando `--raiz` é usado.

**Não reclassifico para FULL por conta própria.** O censo avaliou o estado e
disse PARTIAL; sobrescrever isso com o meu julgamento seria a autoaprovação que
a missão proíbe.
