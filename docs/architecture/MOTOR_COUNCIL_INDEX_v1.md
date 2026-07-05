# NOMOS Motor Council — Technical Index v1

## 1. Status

```text
INDEX_ONLY=true
IMPLEMENTATION_SUMMARY=true
RELEASE_PREP=true
CODE_CHANGED=false
```

> As flags abaixo eram a foto do momento em que este índice foi criado (MC10,
> antes de qualquer tag/release). Elas evoluíram nas fases seguintes; o estado
> **atual** de release está no bloco "Estado pós-release" logo em seguida.
>
> ```text
> TAG_CREATED=false          # (MC10) — a tag foi criada depois, em MC11-RC4
> RELEASE_PUBLISHED=false     # (MC10) — o release foi publicado depois, em MC12-RC4
> PYPI_PUBLISHED=false        # continua verdadeiro: nada publicado no PyPI
> ```

**Estado pós-release (a partir de MC13-RC4):**

```text
RC4_TAG=v1.3.0rc4-motor-council-dry-run
RC4_TAG_COMMIT=10a7cc7
RC4_RELEASE_PUBLISHED=true
RC4_PRERELEASE=true
RC4_LATEST=false
RELEASE_WORKFLOW_RC_GUARD=true
README_PUBLIC_ALIGNMENT=done
PYPI_PUBLISHED=false
```

**Estado de UX/superfícies (a partir de MC19):**

```text
MC14_CLI_SKELETON_DISABLED=PASS
MC15_CLI_DRY_RUN_COMMAND=PASS
MC16_CHAT_COMMAND_DISABLED=PASS
MC17_CHAT_DRY_RUN_SPEC_PLAN=PASS
MC18_CHAT_DRY_RUN_IMPLEMENTATION=PASS
CLI_DRY_RUN_AVAILABLE=true          # nomos conselho simular "..."
CHAT_DRY_RUN_AVAILABLE=true         # /conselho simular ...
OTHER_SUBCOMMANDS_DISABLED=true     # perguntar/revisar/status/modos/explicar/diagnostico
REAL_EXECUTION_AVAILABLE=false
PRODUCTION_READY=false
MC20_SHARED_REDACTION_OUTPUT_SPEC=PASS
MC21_SHARED_REDACTION_HELPER_IMPLEMENTATION=PASS
MC22_CLI_MIGRATION_SAFE_OUTPUT=PASS
MC23_CHAT_MIGRATION_SAFE_OUTPUT=PASS
SHARED_HELPER_IMPLEMENTED=true        # src/nomos/council/safe_output.py
SHARED_HELPER_ADOPTED_BY_CLI=true     # nomos conselho simular (MC22)
SHARED_HELPER_ADOPTED_BY_CHAT=true    # /conselho simular (MC23)
CLI_CHAT_SECURITY_DUPLICATION=RESOLVED # ambas usam o helper; resta só texto humano por superfície
FORBIDDEN_FLAGS_RECONCILED=false      # CLI 8 vs chat 10 — reservado para MC24
```

> A duplicação controlada entre `cli_dry_run.py` e `chat_dry_run.py` está
> especificada para unificação futura em
> `docs/architecture/MOTOR_COUNCIL_SHARED_OUTPUT_REDACTION_SPEC_v1.md` (MC20,
> SPEC-only) — o helper compartilhado ainda **não** foi implementado; o
> refactor é reservado para MC21+.

Este documento é um **índice técnico de consolidação**, não uma especificação
nova nem uma implementação. Ele resume, com referências verificáveis, tudo o
que as fases MC0–MC9 do Motor Council entregaram, mais o estado de release
(MC10–MC13-RC4) e o estado das superfícies de UX (MC14–MC18, alinhado em
MC19). Nenhum arquivo em `src/**` ou `tests/**` foi criado ou alterado para
produzir ou manter este índice.

## 2. Scope

```text
DOCUMENTATION_INDEX=true
RC4_PREPARED=true
REAL_ENGINE_EXECUTION=false
REAL_POLICY=false
REAL_AUDIT=false
REAL_VAULT=false
REAL_APPROVAL=false
CLOUD=false
NETWORK=false
SUBPROCESS=false
PERSISTENCE=false
CLI_IMPLEMENTED=false
CHAT_IMPLEMENTED=false
```

Este índice cobre exclusivamente o que já foi **entregue e validado em CI**
(MC0–MC9). Não antecipa nem valida trabalho de fases futuras (MC10+); onde
fases futuras são mencionadas (seção 19), é apenas como roteiro, não como
trabalho realizado.

## 3. Phase Map MC0–MC9

| Fase | Status | Escopo | STATUS_FINAL |
|---|---|---|---|
| MC0 | PASS | Technical spec (SPEC_ONLY) | `PASS_MOTOR_COUNCIL_SPEC_ONLY` |
| MC1 | PASS | Data models | `PASS_MOTOR_COUNCIL_MC1_DATA_MODELS` |
| MC2 | PASS | Offline simulator | `PASS_MOTOR_COUNCIL_MC2_OFFLINE_SIMULATOR` |
| MC3 | PASS | Local provider contract | `PASS_MOTOR_COUNCIL_MC3_LOCAL_PROVIDER_CONTRACT` |
| MC4 | PASS | Local adapter dry-run | `PASS_MOTOR_COUNCIL_MC4_LOCAL_ADAPTER_DRY_RUN` |
| MC5 | PASS | Local harness fail-closed | `PASS_MOTOR_COUNCIL_MC5_LOCAL_HARNESS_FAIL_CLOSED` |
| MC6 | PASS | Policy gate dry-run | `PASS_MOTOR_COUNCIL_MC6_POLICY_GATE_DRY_RUN` |
| MC7 | PASS | Private audit envelope dry-run | `PASS_MOTOR_COUNCIL_MC7_PRIVATE_AUDIT_ENVELOPE` |
| MC8 | PASS | Orchestrator dry-run | `PASS_MOTOR_COUNCIL_MC8_ORCHESTRATOR_DRY_RUN` |
| MC9 | PASS | CLI/chat UX spec-only | `PASS_MOTOR_COUNCIL_MC9_CLI_CHAT_UX_SPEC_ONLY` |

**Nota sobre MC3**: a fase MC3 teve duas iterações. A primeira
(`MOTOR_COUNCIL_MC3_LOCAL_ENGINE.md`, `STATUS_FINAL=
PASS_MOTOR_COUNCIL_MC3_LOCAL_ENGINE_INTEGRATION`, 606 testes) foi
**superseded** pela segunda (`MOTOR_COUNCIL_MC3_LOCAL_PROVIDER.md`,
`STATUS_FINAL=PASS_MOTOR_COUNCIL_MC3_LOCAL_PROVIDER_CONTRACT`, 608 testes):
`local_engine.py` e seus testes foram removidos e substituídos por
`local_provider.py`, com códigos de falha mais claros, para não deixar dois
provedores paralelos. O relatório `MOTOR_COUNCIL_MC3_LOCAL_ENGINE.md`
permanece no repositório apenas como registro histórico da iteração
substituída; **a canônica é `LOCAL_PROVIDER_CONTRACT`**, e é essa que o
código-fonte atual (`src/nomos/council/local_provider.py`) implementa.

Todas as dez linhas acima (MC0–MC9) estão `PASS` — nenhuma fase terminou em
`WARN` ou `FAIL` nesta trilha.

## 4. Architecture Map

Pipeline efetivamente implementado (todo em dry-run, sem motor real):

```text
CouncilOrchestratorDryRun.run(CouncilOrchestrationInput)
  │
  ├─ 1. INPUT_VALIDATED            (revalidação defensiva de session_id/prompt/max_candidates)
  ├─ 2. LOCAL_PROVIDER_EVALUATED   (LocalCandidateProvider — MC3 local_provider.py,
  │                                  via DryRunAdapterCandidateProvider — MC4 local_adapter.py)
  ├─ 3. CANDIDATES_CREATED        (aliases/candidatos locais, sem engine_id real exposto)
  ├─ 4. SIMULATOR_RAN             (OfflineCouncilSimulator.run_with_candidates — MC2 simulator.py,
  │                                  sobre os modelos puros — MC1 models.py)
  ├─ 5. POLICY_GATE_EVALUATED     (CouncilPolicyGateDryRun — MC6 policy_gate.py, A0–A6)
  ├─ 6. FINAL_ENVELOPE_CREATED    (FinalResponseEnvelope — MC6 policy_gate.py)
  ├─ 7. AUDIT_ENVELOPE_CREATED    (CouncilAuditEnvelopeBuilder — MC7 audit_envelope.py, metadata-only)
  └─ 8. ORCHESTRATION_COMPLETED | ORCHESTRATION_BLOCKED
```

`src/nomos/council/local_harness.py` (MC5, trava `
REAL_LOCAL_ENGINE_EXECUTION_ENABLED = False`) existe **fora** deste fluxo: o
orquestrador (MC8) não o importa em nenhuma circunstância — é o contrato de
execução real bloqueado, reservado para uma fase futura explicitamente
aprovada (ver seção 11).

A UX especificada em MC9 (`docs/architecture/MOTOR_COUNCIL_UX_SPEC_v1.md`)
descreve como um futuro `nomos conselho`/`/conselho` chamaria exatamente este
`CouncilOrchestratorDryRun.run()` como ponto único de composição — mas essa
chamada ainda **não existe em código** (`CLI_IMPLEMENTED=false`,
`CHAT_IMPLEMENTED=false`).

## 5. Files Created

### 5.1 Código (`src/nomos/council/`)

| Arquivo | Fase | Papel |
|---|---|---|
| `models.py` | MC1 | Modelos de dados puros (session, policy, risk, candidate, review, score, arbiter, disagreement, audit) |
| `simulator.py` | MC2 | Simulador offline determinístico (fixtures, sem LLM real) |
| `local_provider.py` | MC3 | Contrato de provedor de candidatos locais (`local:` only) |
| `local_adapter.py` | MC4 | Adaptador de motor local em SPEC/DRY-RUN (`would_execute=false`) |
| `local_harness.py` | MC5 | Harness de execução real, travado por `REAL_LOCAL_ENGINE_EXECUTION_ENABLED = False` |
| `policy_gate.py` | MC6 | Integração dry-run com o Policy Gate A0–A6 |
| `audit_envelope.py` | MC7 | Envelope de auditoria dry-run, metadata-only |
| `orchestrator.py` | MC8 | Orquestrador — compõe as sete peças acima num fluxo único |
| `__init__.py` | MC1–MC8 | Exports públicos do pacote `nomos.council` |

### 5.2 Testes

| Diretório/arquivo | Fases |
|---|---|
| `tests/test_council_models.py` / `test_council_model_security.py` | MC1 |
| `tests/test_council_simulator.py` / `test_council_simulator_security.py` | MC2 |
| `tests/test_council_local_provider.py` / `test_council_local_provider_security.py` | MC3 |
| `tests/test_council_local_adapter.py` / `test_council_local_adapter_security.py` | MC4 |
| `tests/test_council_local_harness.py` / `test_council_local_harness_security.py` | MC5 |
| `tests/test_council_policy_gate_dry_run.py` / `test_council_policy_gate_security.py` | MC6 |
| `tests/test_council_audit_envelope.py` / `test_council_audit_envelope_security.py` | MC7 |
| `tests/council/test_orchestrator.py` / `tests/council/test_orchestrator_security.py` | MC8 (primeira vez em subdiretório `tests/council/`) |

### 5.3 Documentação

| Arquivo | Fase | Papel |
|---|---|---|
| `docs/architecture/MOTOR_COUNCIL_SPEC_v1.md` | MC0 | Especificação técnica canônica (20 seções) |
| `docs/architecture/MOTOR_COUNCIL_UX_SPEC_v1.md` | MC9 | Especificação de UX futura de CLI/chat (21 seções) |
| `docs/architecture/MOTOR_COUNCIL_INDEX_v1.md` | MC10 | Este índice |
| `docs/missions/MOTOR_COUNCIL_SPEC_ONLY_v1.md` | MC0 | Relatório de missão |
| `docs/missions/MOTOR_COUNCIL_MC1_DATA_MODELS.md` | MC1 | Relatório de missão |
| `docs/missions/MOTOR_COUNCIL_MC2_OFFLINE_SIMULATOR.md` | MC2 | Relatório de missão |
| `docs/missions/MOTOR_COUNCIL_MC3_LOCAL_ENGINE.md` | MC3 (substituída) | Relatório histórico da iteração superseded |
| `docs/missions/MOTOR_COUNCIL_MC3_LOCAL_PROVIDER.md` | MC3 (canônica) | Relatório de missão |
| `docs/missions/MOTOR_COUNCIL_MC4_LOCAL_ADAPTER_DRY_RUN.md` | MC4 | Relatório de missão |
| `docs/missions/MOTOR_COUNCIL_MC5_LOCAL_HARNESS_FAIL_CLOSED.md` | MC5 | Relatório de missão |
| `docs/missions/MOTOR_COUNCIL_MC6_POLICY_GATE_DRY_RUN.md` | MC6 | Relatório de missão |
| `docs/missions/MOTOR_COUNCIL_MC7_PRIVATE_AUDIT_ENVELOPE.md` | MC7 | Relatório de missão |
| `docs/missions/MOTOR_COUNCIL_MC8_ORCHESTRATOR_DRY_RUN.md` | MC8 | Relatório de missão |
| `docs/missions/MOTOR_COUNCIL_MC9_CLI_CHAT_UX_SPEC_ONLY.md` | MC9 | Relatório de missão |
| `docs/missions/MOTOR_COUNCIL_MC10_DOCUMENTATION_INDEX_RC4_PREP.md` | MC10 | Relatório desta fase |
| `docs/missions/RELEASE_NOTES_v1.3.0rc4_MOTOR_COUNCIL_DRY_RUN.md` | MC10 | Release notes RC4 (rascunho) |
| `docs/missions/GITHUB_RELEASE_v1.3.0rc4_MOTOR_COUNCIL_DRY_RUN.md` | MC10 | GitHub Release RC4 (rascunho) |

## 6. Security Guarantees

Válido para **todo** o pacote `nomos.council` (MC1–MC8), provado por teste AST
(análise de `import`/`ImportFrom`) e por busca textual em cada módulo, não por
convenção:

- Nenhum módulo importa rede (`socket`/`http`/`urllib`/`requests`/`httpx`/…).
- Nenhum módulo importa `subprocess`/`threading`/`multiprocessing`/`asyncio`.
- Nenhum módulo importa SDKs cloud (`openai`/`anthropic`/`google.generativeai`/…).
- Nenhum módulo importa motores reais (`ollama`/`llama_cpp`/`transformers`/
  `torch`/`nomos.runtime`/…).
- Nenhum módulo toca filesystem (`pathlib`/`os`/`io`/…) nem usa
  `os.environ`/`os.getenv`.
- Nenhum módulo usa `time`/`datetime.now`/`random`/`secrets` (determinismo).
- Nenhum módulo importa `nomos.kernel.policy`/`vault`/`audit`/`approval` reais.
- Nenhum módulo importa ou referencia `nomos.agents`/`nomos.skills`/`nomos.router`.
- Nenhum módulo menciona `nomos conselho` ou `/conselho` (CLI/chat reais).
- Todos os módulos usam só stdlib (`dataclasses`, `enum`, `typing`, `json`,
  `__future__`) e outros submódulos de `nomos.council` já validados.

## 7. Dry-run Guarantees

- `dry_run=true` é forçado por `__post_init__` (não por argumento) em todo
  dataclass que carrega essa flag (MC4 `LocalEngineExecutionPlan`, MC6
  `CouncilGateDecision`, MC7 `CouncilAuditEnvelope`, MC8
  `CouncilOrchestrationTrace`/`Result`).
- `would_execute=false` sempre (MC4, MC8); `would_call_real_policy=false` e
  `would_request_approval=false` sempre (MC6); `would_write_audit=false`
  sempre (MC7, MC8).
- Determinismo: mesma entrada ⇒ mesma saída, byte a byte no JSON, provado por
  teste em MC2–MC8.
- Prompt nunca aparece em `repr`/`to_dict`/`to_json` de nenhum modelo — apenas
  `prompt_chars` (tamanho), a partir do MC1.

## 8. Private Mode Guarantees

- `private_mode=true` ⇒ `persist_allowed=false` em: `CouncilSession` e
  `CouncilAuditRecord` (MC1), `FinalResponseEnvelope` (MC6),
  `CouncilAuditEnvelope`/todos os envelopes do builder (MC7), e propagado pelo
  orquestrador (MC8) para o envelope final e para **todos** os envelopes de
  auditoria simultaneamente.
- Validação ativa: um envelope de auditoria que declare `persist_allowed=true`
  sob modo privado é **rejeitado** (`AUDIT_ENVELOPE_PRIVATE_PERSIST_DENIED`,
  MC7), não apenas ignorado.
- Defesa em profundidade: o orquestrador (MC8) roda uma checagem adicional
  (`_verificar_persist_privado`) após montar o envelope final e o resultado de
  auditoria, confirmando que nenhum dos dois libera persistência sob modo
  privado — na prática inalcançável pelos modelos reais, mas exercida
  diretamente por teste.

## 9. Policy Gate Guarantees

- Toda resposta final simulada passa pelo `CouncilPolicyGateDryRun` (MC6)
  antes de qualquer envelope ser criado — não existe caminho que libere
  conteúdo sem consultar o gate.
- Regras fail-closed determinísticas: árbitro bloqueado, conteúdo final
  vazio, risco A6, aprovação humana exigida, dado sensível, e risco A3–A5 ⇒
  todos negados; apenas A0/A1/A2 sem as condições acima ⇒ liberado.
- `POLICY_GATE_EVALUATED` é sempre anterior a `FINAL_ENVELOPE_CREATED` no
  trace do orquestrador (MC8), provado por teste em múltiplos cenários,
  inclusive bloqueados.
- Gate negado ⇒ `FinalResponseEnvelope.content=None`; conteúdo, quando
  liberado, nunca é serializado (`to_dict` sempre `content=null`) nem
  aparece em `repr`.

## 10. Audit Envelope Guarantees

- `AUDIT_ENVELOPE_CREATED` é sempre posterior a `POLICY_GATE_EVALUATED` no
  trace do orquestrador (MC8), provado por teste.
- Metadata é **só contagens e failure_code**: prompt, conteúdo de
  candidato/final, `engine_id` e qualquer chave/valor de aparência sensível
  (`api_key`/`token`/`bearer`/…) nunca aparecem em `to_dict`/`to_json`/`repr`/
  `warnings` — bloqueado ativamente por `AUDIT_ENVELOPE_SENSITIVE_METADATA`
  quando detectado (MC7, e checagem local equivalente em MC8 para a metadata
  de cada etapa do trace).
- Um envelope que declare `would_write_audit=true` ou `redacted=false` é
  rejeitado por construção/validação (MC7).
- `CouncilAuditRedactionProfile.for_private()` liga redação máxima
  (`redact_scores_detail=True` também) quando `private_mode=true`.

## 11. Harness / Real Execution Lock

```python
# src/nomos/council/local_harness.py
REAL_LOCAL_ENGINE_EXECUTION_ENABLED = False
```

- Constante literal, no topo do módulo, atribuída **uma única vez** (provado
  por teste AST). Não vem de `env`, config ou argumento — o módulo não lê
  variáveis do sistema.
- Não existe nenhuma função pública para ligá-la (nada de
  `enable`/`activate`/`unlock`/`set_enabled`) — provado por teste de
  introspecção (`dir()`) além da checagem AST.
- `LocalExecutionHarness.execute()` sempre devolve `allowed=false`,
  `executed=false`, `candidate=null`, com o código `REAL_EXECUTION_DISABLED`
  (ou `REAL_EXECUTION_ENGINE_NOT_LOCAL` para motor não-local, barrado antes
  mesmo da trava). Setar uma variável de ambiente com o mesmo nome da
  constante **não tem efeito** (testado explicitamente).
- **O orquestrador (MC8) não importa este módulo em nenhuma circunstância** —
  nem a constante, nem `LocalExecutionHarness`, nem qualquer `.execute(`
  aparecem em `orchestrator.py`. Não há caminho, direto ou indireto, para
  execução real através do pipeline hoje implementado.
- Remover a trava exigiria uma edição explícita e auditável deste arquivo —
  não uma mudança de configuração, dado ou runtime.

## 12. UX Specification Summary

`docs/architecture/MOTOR_COUNCIL_UX_SPEC_v1.md` (MC9, 21 seções, SPEC-only,
nada implementado) especifica, para uma implementação futura:

- Comandos CLI futuros `nomos conselho perguntar|revisar|simular|status|
  explicar-ultima-decisao|modos|diagnostico` (aliases `nomos council
  ask|simulate|status`) e flags (`--modo`, `--privado`, `--local-only`,
  `--sem-memoria`, `--simular`, `--explicar`, `--json`, `--iniciante`,
  `--avancado`), com `COMMANDS_NOT_IMPLEMENTED_IN_MC9=true` declarado.
- Comandos de chat futuros `/conselho perguntar|revisar|simular|status|modos|
  explicar|privado on|off`, com as mesmas garantias de não-bypass da CLI.
- UX dos 4 modos do Council, do modo privado (mensagem + JSON), do
  local-only/cloud-denied, do Policy Gate (bloqueio nunca vaza conteúdo), do
  audit envelope (metadata-only), de um formato fixo de erro
  `[NOMOS-MC-XXX]` aplicado a 10 códigos mínimos, dos modos iniciante/
  avançado, da explicação de dry-run, e de uma futura aprovação humana (ainda
  sem implementar).
- 5 exemplos completos de uso e um plano de 15 testes futuros exatos, para
  quando a implementação (`MC12-UX`+ — ver reconciliação de numeração na
  seção 19) começar.
- Fases futuras de UX, **renumeradas em MC11-RC4** para não colidir com a
  trilha de release engineering: `MC10` (índice + RC4) → `MC11-RC4` (tag
  RC4) → `MC12-UX` (CLI skeleton desabilitado) → `MC13-UX` (CLI dry-run) →
  `MC14-UX` (chat SPEC/disabled) → `MC15-UX` (chat dry-run) → `MC16-UX`
  (aprovação humana dry-run) → `MC17-UX` (revisão do harness real). A
  numeração original (MC11–MC16 para a trilha de UX) foi atualizada
  diretamente em `MOTOR_COUNCIL_UX_SPEC_v1.md` seção 20; ver seção 19 abaixo
  para o histórico da reconciliação.

## 13. Test Growth

| Fase | Testes novos | Suíte completa |
|---|---|---|
| MC0 / Spec baseline | — | 520 |
| MC1 | +31 | 551 |
| MC2 | +26 | 577 |
| MC3 (iteração `local_engine`, superseded) | +29 | 606 (descartado) |
| MC3 (`local_provider`, canônica — líquido sobre MC2) | +31 | 608 |
| MC4 | +29 | 637 |
| MC5 | +26 | 663 |
| MC6 | +30 | 693 |
| MC7 | +31 | 724 |
| MC8 | +54 | 778 |
| MC9 | +0 (docs-only) | 778 |

Confirmado nesta fase (MC10): `pytest -q` local reporta **778 passed**,
idêntico ao valor registrado ao final do MC9 — nenhum teste foi adicionado,
removido ou alterado neste índice.

## 14. CI Evidence

| Item | Resultado |
|---|---|
| Último commit MC9 | `378cece` (docs(council): document MC9 UX spec-only phase) |
| CI_STATUS (378cece) | PASS |
| CI_JOBS (378cece) | 17/17 |
| PYTEST (378cece) | PASS_778 |
| Breakdown dos 17 jobs | `testes` (pytest × 3 SOs × 4 versões Python = 12) + `cobertura (informativa)` + `mypy (informativo)` + `smoke pós-instalação (wheel)` × 3 SOs |

O commit e o CI desta própria fase (MC10) estão registrados no relatório
`docs/missions/MOTOR_COUNCIL_MC10_DOCUMENTATION_INDEX_RC4_PREP.md` (seção 7),
verificados após o push — este índice não se auto-referencia com um commit
que ainda não existia no momento em que foi escrito.

## 15. Known Sandbox Quirks

Documentados honestamente para não serem confundidos com falha do pacote:

- `python -m build` no diretório montado do sandbox (FS fuse) estoura
  `RecursionError` na limpeza de tempdir do backend de build. **Não é falha
  do pacote**: copiar a árvore para `/tmp` e rodar `TMPDIR=/tmp python3 -m
  build --wheel` lá sempre funciona, e o job `smoke pós-instalação (wheel)`
  do CI builda nos 3 sistemas operacionais em runners limpos — essa é a
  validação autoritativa.
- `pytest --cov` no mesmo diretório montado falha ao tentar apagar um
  `.coverage` pré-existente (`PermissionError: Operation not permitted`),
  mesma classe de quirk; resolvido rodando a suíte com cobertura a partir de
  uma cópia em `/tmp`.
- `.git/index.lock` ocasionalmente fica para trás e não pode ser removido via
  `rm -f`, `os.remove()` do Python, nem pela ferramenta de exclusão de
  arquivos do Cowork (todas retornam permissão negada para o diretório
  montado do sandbox). Resolvido operando diretamente no Mac real via Desktop
  Commander (mesmo arquivo, mesmo caminho, sem esse bloqueio) — nenhum
  histórico de commit foi alterado para contornar isso.
- Verificação de CI via API do GitHub por polling (`curl` em loop) pode
  ocasionalmente travar numa chamada de rede sem `--max-time`; resolvido
  emitindo uma nova checagem pontual com timeout explícito em vez de
  aguardar indefinidamente o loop original.

Em todos os casos acima: o pacote, os testes e o CI em runners limpos
passaram normalmente — os quirks são do ambiente de execução do sandbox, não
do código entregue.

## 16. Non-goals / Not Implemented

Confirmado, sem exceção, em MC0–MC9:

- Nenhum motor real, Ollama, llama.cpp, transformers ou torch foi chamado.
- Nenhuma chamada de rede, subprocess, thread, processo ou timer foi criada.
- Nenhum SDK cloud (OpenAI/Anthropic/Gemini/…) foi importado ou chamado.
- Nenhuma integração com `policy`/`audit`/`vault`/`approval` reais do kernel.
- Nenhuma persistência em disco foi realizada pelo pacote `nomos.council`.
- Nenhum CLI real (`nomos conselho`) nem chat command real (`/conselho`)
  existe — apenas a especificação de UX (MC9).
- Nenhum agente ou skill usa o Council.
- Nenhuma alteração do roteador global, dos agentes, das skills ou do
  runtime do NOMOS.
- Nenhuma tag, release do GitHub ou publicação no PyPI foi criada em
  qualquer fase MC0–MC9.

## 17. Residual Risks

Consolidado das seções "riscos remanescentes" de cada relatório de fase:

- ~~**Numeração de fases divergente**~~ — **RESOLVIDO em MC11-RC4**: a
  colisão entre "MC11 — CLI skeleton desabilitado" (trilha UX, prevista pelo
  MC9) e "MC11 — RC4 Tag Preparation/Validation" (trilha release engineering)
  foi reconciliada explicitamente: `MC11-RC4` passou a designar
  exclusivamente a trilha de release engineering; toda a trilha de UX foi
  renumerada para `MC12-UX`–`MC17-UX` diretamente em
  `MOTOR_COUNCIL_UX_SPEC_v1.md` (seção 20). Ver seção 19 abaixo.
- **Inconsistência cosmética de `session_id`** (MC8): o `session_id` visível
  nos envelopes de auditoria continua sendo o identificador interno fixo do
  simulador (`offline-sim`), não o `session_id` do chamador — o gate e o
  envelope final já usam o do chamador. Não é uma falha de segurança (nada
  vaza), mas é uma divergência de contrato entre módulos que uma futura
  unificação deveria corrigir.
- **Provider ainda é fake determinístico** (MC3/MC4): nenhum motor local real
  (ex.: llama.cpp embutido) foi integrado; quando isso acontecer, a nova
  camada precisará provar, também por teste AST, que não abre rede.
- **Lista de chaves sensíveis é explícita, não reaproveitada do kernel**
  (MC7): um nome de campo novo e imprevisto no futuro poderia escapar da
  redação; recomenda-se reusar o `redact` do `kernel/audit` quando a
  integração real acontecer.
- **Spec de UX é normativa, não vinculante por código** (MC9): nada impede
  uma implementação futura de divergir dela; a mitigação é a disciplina
  `implementation-loop-100`, que exige revisão da spec antes de qualquer
  código de `MC12-UX`+.
- **Códigos de erro `[NOMOS-MC-XXX]` são provisórios** (MC9): quando a
  implementação real de CLI/chat começar, pode ser necessário reconciliá-los
  com um esquema de códigos de erro mais amplo do NOMOS.
- **Nenhuma tag/release ainda existe para este trabalho**: RC4 está apenas
  preparado em rascunho (seções 13–14 do mission report MC10); a decisão de
  efetivamente criar a tag e publicar o release é de uma fase futura
  explicitamente aprovada.

## 18. RC4 Readiness Checklist

| Item | Status |
|---|---|
| Todas as fases MC0–MC9 com `STATUS_FINAL=PASS` | ✅ |
| Suíte de testes estável (778, sem flutuação) | ✅ |
| CI verde 17/17 no último commit conhecido antes desta fase (378cece) | ✅ |
| Garantias de segurança (AST) provadas em todos os módulos `nomos.council` | ✅ |
| Nenhum motor/policy/audit/vault real tocado | ✅ |
| Modo privado provado fail-closed ponta a ponta | ✅ |
| Harness de execução real travado e não referenciado pelo orquestrador | ✅ |
| Índice técnico único (este documento) | ✅ |
| Release notes RC4 (rascunho) preparadas | ✅ (ver `RELEASE_NOTES_v1.3.0rc4_MOTOR_COUNCIL_DRY_RUN.md`) |
| GitHub Release RC4 (rascunho) preparado | ✅ (ver `GITHUB_RELEASE_v1.3.0rc4_MOTOR_COUNCIL_DRY_RUN.md`) |
| CHANGELOG atualizado com a preparação | ✅ |
| Tag `v1.3.0rc4-motor-council-dry-run` criada | ✅ criada em MC11-RC4, aponta para o commit validado |
| GitHub Release publicado | ✅ publicado automaticamente pelo workflow ao enviar a tag; corpo técnico aplicado em MC12-RC4 (`prerelease=true`, não-latest, título e conteúdo corrigidos) |
| Publicação no PyPI | ⏳ pendente — fora do escopo desta fase |
| Reconciliação da numeração MC11+ (trilha release vs. trilha UX) | ✅ resolvida em MC11-RC4 (ver seção 19) |
| `release.yml` ajustado para não precisar de correção pós-tag | ✅ resolvido em MC12-RC4 — step `Resolve release flags` decide `prerelease`/`make_latest` a partir do nome da tag (`*rc*` ⇒ pre-release, não-latest) |

## 19. Future Roadmap

Duas trilhas independentes, agora **reconciliadas** (MC11-RC4) para não
colidir em numeração:

**Trilha RC — Release engineering**:
`MC10` (índice + RC4 prep) → `MC11-RC4` (validar CI/ancestry e criar a tag
`v1.3.0rc4-motor-council-dry-run`, sem publicar release automaticamente) →
`MC12-RC4` (GitHub Release Publication — pre-release, `latest=false`) →
futura fase de publicação no PyPI.

**Trilha UX — Implementação de CLI/chat** (prevista pela seção 20 do
`MOTOR_COUNCIL_UX_SPEC_v1.md`, renumerada em MC11-RC4):
`MC12-UX` (CLI skeleton desabilitado) → `MC13-UX` (CLI dry-run) → `MC14-UX`
(chat SPEC/disabled) → `MC15-UX` (chat dry-run) → `MC16-UX` (aprovação
humana dry-run) → `MC17-UX` (revisão do harness real antes de qualquer
execução real).

As duas trilhas agora têm numeração disjunta (`MCxx-RC4` vs. `MCxx-UX`) e
podem progredir independentemente sem ambiguidade em relatórios futuros. Esta
reconciliação foi decidida e aplicada na fase `MC11-RC4` (ver
`docs/missions/MOTOR_COUNCIL_MC11_RC4_TAG_PREPARATION.md`); nenhuma missão
futura precisa re-decidir este ponto — apenas seguir a numeração disjunta
acima.

**O que a trilha UX efetivamente entregou (atualizado em MC19):** as fases
executadas foram `MC14-UX` (CLI skeleton desabilitado), `MC15-UX` (CLI
dry-run `nomos conselho simular`), `MC16-UX` (chat skeleton desabilitado),
`MC17-UX` (spec do chat dry-run) e `MC18-UX` (chat dry-run `/conselho
simular`). Portanto **existem hoje duas superfícies dry-run em paralelo** —
CLI (`src/nomos/council/cli_dry_run.py`) e chat
(`src/nomos/council/chat_dry_run.py`) — que compartilham o mesmo contrato
(chamar só o `CouncilOrchestratorDryRun`, redigir a saída, nunca
`result.to_dict()`) mas **não** o mesmo código. Essa **duplicação é
controlada e intencional**: uma eventual unificação (helper comum de
parsing/redação) deve ser uma **fase de refactor seguro separada**, nunca
combinada com qualquer habilitação de execução real. Próxima fase recomendada
para isso: `MC20 — Shared Redaction/Output Helper SPEC` (desenho da
unificação, ainda sem refatorar).

## 20. Acceptance Criteria

| Critério da missão MC10 | Atendido |
|---|---|
| Índice técnico criado | ✅ `docs/architecture/MOTOR_COUNCIL_INDEX_v1.md` |
| Release notes RC4 preparadas | ✅ |
| GitHub Release draft RC4 preparado | ✅ |
| Relatório MC10 criado | ✅ `docs/missions/MOTOR_COUNCIL_MC10_DOCUMENTATION_INDEX_RC4_PREP.md` |
| CHANGELOG atualizado | ✅ |
| Nenhum arquivo de código alterado | ✅ (`git diff --stat` restrito a `docs/` e `CHANGELOG.md`) |
| Nenhum teste alterado | ✅ |
| PYTEST continua 778 | ✅ |
| CI remoto passa 17/17 | ver relatório MC10 (verificado após push) |
| Nenhuma tag criada | ✅ |
| Nenhum release criado | ✅ |
| Nenhum PyPI publicado | ✅ |
| Nenhum comando real implementado | ✅ |
| Nenhuma execução real habilitada | ✅ |
