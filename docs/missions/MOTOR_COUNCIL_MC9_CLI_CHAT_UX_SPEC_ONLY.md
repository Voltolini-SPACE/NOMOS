# MOTOR COUNCIL MC9 — CLI/CHAT UX SPEC-ONLY

## 1. Status final

STATUS_FINAL=PASS_MOTOR_COUNCIL_MC9_CLI_CHAT_UX_SPEC_ONLY

Especificação canônica de UX para os futuros `nomos conselho`/`nomos council`
(CLI) e `/conselho` (chat) criada em
`docs/architecture/MOTOR_COUNCIL_UX_SPEC_v1.md` (21 seções), cobrindo
comandos, aliases, flags, mensagens de erro/bloqueio, modos, dry-run, private
mode, Policy Gate, audit envelope, aprovação humana futura, exemplos, plano de
testes futuros e fases de implementação futuras. Nenhum código, CLI, chat
command, teste ou módulo do Council foi criado, alterado ou tocado.

## 2. Baseline

| Item | Resultado |
|---|---|
| BASELINE_HEAD | 52b0bb3 |
| BASELINE_TAG | v1.2.0rc3-audit-anchored-29-g52b0bb3 |
| GIT_STATUS | CLEAN (antes das mudanças) |
| GIT_FSCK | PASS (1 commit dangling pré-existente, benigno) |
| RUFF | PASS |
| PYTEST | PASS_778 |
| BUILD | PASS_IN_TMP_SANDBOX_FS_QUIRK |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | WARN (LOG_LEGACY_UNANCHORED, esperado) |

`python -m build` no diretório montado do sandbox estoura `RecursionError` na
limpeza de tempdir do backend (mesmo quirk de FS fuse já registrado nas fases
anteriores, não do pacote); o wheel compila normalmente em `/tmp`.

## 3. Escopo

```text
UX_SPEC_ONLY=true
CLI_IMPLEMENTED=false
CHAT_IMPLEMENTED=false
REAL_ENGINE_EXECUTION=false
REAL_POLICY=false
REAL_AUDIT=false
PERSISTENCE=false
```

## 4. Documentos criados

| Arquivo | Status |
|---|---|
| `docs/architecture/MOTOR_COUNCIL_UX_SPEC_v1.md` | criado (21 seções) |
| `docs/missions/MOTOR_COUNCIL_MC9_CLI_CHAT_UX_SPEC_ONLY.md` | criado (este relatório) |
| `docs/architecture/MOTOR_COUNCIL_SPEC_v1.md` | atualizado — apenas 1 parágrafo apontando para a nova spec de UX e observando a evolução da numeração de fases; nenhum conteúdo substantivo alterado |

## 5. O que foi especificado

- **Comandos CLI futuros**: `nomos conselho perguntar|revisar|simular|status|
  explicar-ultima-decisao|modos|diagnostico`, com aliases `nomos council
  ask|simulate|status`, e `COMMANDS_NOT_IMPLEMENTED_IN_MC9=true` declarado
  explicitamente.
- **Flags futuras**: `--modo {rapido,balanceado,critico,paranoico}`,
  `--privado`, `--local-only`, `--sem-memoria`, `--simular`, `--explicar`,
  `--json`, `--iniciante`, `--avancado` — com regras de implicação
  (`--modo paranoico` ⇒ `--local-only --privado --sem-memoria`) e de
  fail-closed em conflito.
- **Comandos de chat futuros**: `/conselho perguntar|revisar|simular|status|
  modos|explicar|privado on|off`, com as mesmas garantias de não-bypass da
  CLI.
- **UX dos 4 modos** do Council (rápido/balanceado/crítico/paranoico),
  mapeados 1:1 para os `CouncilMode` já implementados.
- **UX de modo privado**: mensagem humana fixa + JSON (`persist_allowed:
  false`, `content_redacted: true`, `audit_metadata_only: true`).
- **UX local-only/cloud-denied**: mapeamento dos 3 failure codes existentes
  (`NO_ELIGIBLE_LOCAL_ENGINE`/`CLOUD_BLOCKED_BY_LOCAL_LOCK`/
  `SENSITIVE_DATA_CLOUD_DENIED`) para mensagens humanas.
- **UX do Policy Gate**: exemplo fixo de bloqueio, com as 5 regras de não
  vazamento (sem conteúdo bloqueado, sem candidato vencedor, sem prompt
  sensível, sem sugerir execução real, sem linguagem de sucesso).
- **UX do audit envelope**: só metadata-only (`envelope_count`,
  `failure_code`, `redaction_profile`, `persist_allowed`), nunca conteúdo.
- **Mensagens de erro**: formato fixo `[NOMOS-MC-XXX]` + causa + ação +
  detalhe técnico, aplicado às 10 mensagens mínimas exigidas
  (`ORCH_PROVIDER_FAILED`, `ORCH_NO_CANDIDATES`, `ORCH_POLICY_GATE_DENIED`,
  `ORCH_AUDIT_ENVELOPE_DENIED`, `ORCH_PRIVATE_MODE_PERSIST_DENIED`,
  `GATE_A6_DENIED`, `GATE_REQUIRES_APPROVAL`,
  `GATE_SENSITIVE_DATA_REQUIRES_STRICT_MODE`, `REAL_EXECUTION_DISABLED`,
  `AUDIT_ENVELOPE_SENSITIVE_METADATA`).
- **Modo iniciante/avançado**: mensagens simples vs. trace redigido
  (`trace_order=[...]`), com as mesmas 8 garantias já provadas em dry-run
  pelo orquestrador MC8 (sem prompt, sem conteúdo, sem `engine_id` privado,
  `dry_run=true`, `would_execute=false`, `would_write_audit=false`).
- **Explicação de dry-run**: bloco `DRY_RUN=true/REAL_ENGINE_EXECUTION=false/
  REAL_POLICY=false/REAL_AUDIT=false`, linguagem proibida vs. permitida.
- **Aprovação humana futura**: mensagem fixa + 4 regras (nunca simulada como
  real, nonce/envelope/escopo, não libera cloud sozinha, respeita modo
  privado) — **sem implementar**.
- **5 exemplos completos**: pergunta balanceada, modo privado, modo
  paranoico, gate negado, chat futuro — cada um com comando, saída humana,
  saída JSON (quando aplicável) e observação de segurança.
- **Plano de testes futuros**: 15 nomes exatos, para quando a implementação
  (MC11+) começar.
- **Fases futuras**: MC10 (índice + RC4) → MC11 (CLI skeleton desabilitado)
  → MC12 (CLI dry-run) → MC13 (chat SPEC/disabled) → MC14 (chat dry-run) →
  MC15 (aprovação humana dry-run) → MC16 (revisão do harness real).

## 6. O que NÃO foi implementado

Confirmado:
- sem CLI real
- sem chat command real
- sem motor real
- sem policy real
- sem audit real
- sem vault real
- sem persistência
- sem tags
- sem release

## 7. Validação final

| Item | Resultado |
|---|---|
| RUFF | PASS |
| PYTEST | PASS_778 (inalterado — nenhum teste tocado) |
| BUILD | PASS_IN_TMP_SANDBOX_FS_QUIRK |
| DOUTOR / PYTHON_M_NOMOS_DOUTOR | PASS / PASS |
| LOGS_VERIFY | WARN (LOG_LEGACY_UNANCHORED, esperado) |
| GIT_FSCK | PASS |
| GIT_STATUS | CLEAN |
| Arquivos de código alterados | 0 (`git diff --stat` restrito a `docs/`) |
| CI_STATUS | PASS |
| CI_JOBS | 17/17 |

## 8. Riscos remanescentes

- Esta spec é normativa, mas não vinculante por código — nada impede uma
  implementação futura de divergir dela; a mitigação é a própria disciplina
  `implementation-loop-100`, que exige revisão da spec antes de qualquer
  código de MC11+.
- Os códigos `[NOMOS-MC-XXX]` (403, 410, 411, etc.) são provisórios — quando
  a implementação real começar (MC12), pode ser necessário reconciliá-los com
  um esquema de códigos de erro mais amplo do NOMOS (fora do escopo desta
  spec, que cobre só o Council).
- A tabela de fases da seção 18 do `MOTOR_COUNCIL_SPEC_v1.md` (MC0–MC7
  original) ficou desatualizada frente à numeração real (MC1–MC9 hoje); o
  ponteiro adicionado nesta missão remedia isso parcialmente, mas uma
  consolidação completa do índice de fases é recomendada para MC10.

## 9. Próximo passo recomendado

MC10 — Documentation Index + Release Candidate Preparation, consolidando
MC0–MC9 num índice técnico único e preparando o RC4, ainda sem publicar
release automaticamente.
