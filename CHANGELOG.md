# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/). Datas em UTC.

## [Unreleased] — 2026-07-05 (Motor Council — Fases MC10–MC27 + site: contrato único de flags proibidas, site com brandbook congelado e update agent read-only)

### Added (ARBITRAGEM + MC-VALIDACAO-E2E)
- **Arbitragem real entre motores** (`cognition/arbitragem.py` + CLI
  `nomos motores arbitrar "<pergunta>"`): motores prontos geram candidatos
  reais, juízes cegos pontuam, árbitro converge na melhor execução; fail-closed
  e honesto (sem motor pronto ⇒ bloqueia e explica; `final_content` sempre de
  candidato real). Local-first; nuvem só com opt-in. 16 testes novos.
- **Site expandido**: recursos, motores & integrações, agentes, skills e escada
  de risco A0–A6 na landing (missão SITE_EXPAND, brandbook congelado preservado).
- `tests/test_missao_validacao_anti_regressao.py`: 6 contratos — trava de
  execução real do council, integridade (SHA-256) do brandbook congelado, docs
  essenciais presentes, cobertura do `.gitignore`, proibição de `pip install
  nomos` puro nos docs oficiais, coerência de versão pyproject ↔ pacote.

### Fixed (MC-VALIDACAO-E2E)
- **Docs e site não recomendam mais `pip install nomos` puro** — o nome `nomos`
  no PyPI pertence a projeto de terceiros (dowhiledev, "multi-step agent
  framework"); seguir o manual antigo instalaria outro software. Instalação
  oficial passa a ser via GitHub/instaladores, com aviso explícito (README,
  manual de instalação, brandbook §5, site, `docs/INSTALL.md`).
- README: contagem de testes desatualizada ("884" → "mais de 1.100").
- `pyproject.toml`: URL do Changelog corrigida (`blob/main/CHANGELOG.md`;
  a anterior apontava para `nomos/CHANGELOG.md`, caminho inexistente no repo).
- `docs/INSTALL.md`: exemplo de wheel com versão fixa 0.12.0 → placeholder.

### Added (MC25–MC27)
- **Site NOMOS** (`site/`): landing estática com brandbook congelado
  (`docs/brand/`), página 404, assets e `preview.py`; guia de instalação em
  `docs/installation/` (MC25; polish/rebrand em `docs/missions/SITE_*`).
- **NOMOS Update Agent** (`tools/nomos_update_agent.py`, MC27.0): agente
  **read-only/proposal-only** de consistência de documentação. `--check
  [--json]` funciona como gate de CI (exit 0/1, campos estáveis,
  `real_execution_enabled=false`, `auto_push_enabled=false`); `--diff [--json]`
  propõe patches sem escrever (`PROPOSTA_DIFF_ONLY`, `NO_WRITE`,
  `HUMAN_APPROVAL_REQUIRED`); `--apply` permanece bloqueado fail-closed.
  Contrato em `docs/governance/NOMOS_UPDATE_AGENT.md`. 75 testes novos
  (MC25 deliverables + MC26 check + MC27 diff). Suíte: 1024 → 1114.
- **Higiene de repo**: `.gitignore` ignora diretórios de extração de
  sdist/build (`/nomos-[0-9]*/`) e `.DS_Store`; `conftest.py` raiz evita
  "import file mismatch" na coleta do pytest.

### Changed (MC24)
- Reconciled the Motor Council dry-run **forbidden flags** contract between CLI
  and chat (decisão **A** — unificar): as duas superfícies passam a consumir o
  **mesmo** conjunto de 10 flags de uma fonte única testável,
  `src/nomos/council/forbidden_flags.py` (`FORBIDDEN_FLAGS` +
  `is_forbidden_flag`/`find_forbidden`). A CLI, que listava 8, passou a 10
  (`--vault-real`/`--engine-real` deixam de ser tratadas como *desconhecidas* e
  passam a ser *proibidas*, como no chat); `cli_dry_run.py` e `chat_dry_run.py`
  agora referenciam o **mesmo objeto** do contrato, eliminando a divergência
  herdada (documentada em MC20/MC22/MC23). Comportamento observável para o
  usuário: recusa fail-closed idêntica (mensagem, exit code, sem eco) nas duas
  superfícies para as 10 flags.

### Security (MC24)
- Detecção por **igualdade estrita** (nunca prefixo/substring): flags parecidas
  mas legítimas (`--realmente`, `--enabled`, `--cloudy`) não geram falso
  positivo; seguem recusadas como *desconhecidas* pelo parser. O dry-run segue
  fail-closed; o prompt e a flag nunca são ecoados; a mensagem humana não usa
  jargão; o JSON técnico preserva a estrutura segura. 72 testes novos
  (contrato + paridade CLI/chat + comportamento + pureza AST + guarda
  anti-divergência que impede hardcodar a lista fora da fonte única). Suíte:
  952 → 1024.

### Not changed (MC24)
- `safe_output.py` **não** foi alterado (o contrato de flags é ortogonal à saída
  segura); nenhuma execução real habilitada; `.github/` e `pyproject.toml`
  intocados; nenhuma tag, release ou publicação PyPI.

### Changed (MC23)
- Migrated the Motor Council chat dry-run output to the shared safe output
  helper: `/conselho simular` agora usa `build_safe_output` +
  `render_json_output` (`src/nomos/council/safe_output.py`) como fonte da
  estrutura segura e do JSON, em vez de montar o JSON à mão. O `--json` do chat
  passou de 8 para 10 campos (adição compatível de `interface`/`mode`),
  alinhando com o CLI (MC22).
- Improved chat dry-run human messages for non-technical users: resposta mais
  simples e amigável ("Simulação segura concluída. Nada foi executado de
  verdade. Nada foi salvo. Nenhum dado sensível foi exibido."), sem jargão; o
  bloco técnico `DRY_RUN=true`/`REAL_*` fica sob "Status:" e os detalhes
  completos no `--json`.

### Security (MC23)
- Chat dry-run output remains redacted and emits only approved safe scalar
  fields: o prompt nunca é ecoado, o resultado do orquestrador nunca é
  serializado (sem `to_dict`/`repr`/`vars`/`asdict`), mensagens não-`/conselho`
  seguem retornando `None` e o harness/policy/vault/audit reais não são
  chamados. 15 testes novos (migração + UX + regressão). Suíte: 937 → 952.

### Not changed (MC23)
- CLI dry-run was not changed in this phase (`cli_dry_run.py`/`cli.py` intocados)
  e o helper `safe_output.py` não foi alterado.
- No real engine execution enabled.
- No PyPI publication; nenhuma tag ou release criada.

### Changed (MC22)
- Migrated the Motor Council CLI dry-run output to the shared safe output
  helper: `nomos conselho simular` agora usa `build_safe_output` +
  `render_json_output` (`src/nomos/council/safe_output.py`) como fonte da
  estrutura segura e do JSON, em vez de montar o JSON à mão. O `--json` do CLI
  passou de 8 para 10 campos (adição compatível de `interface`/`mode`).
- Improved CLI dry-run human messages for non-technical users: saída mais
  simples e amigável ("Simulação segura concluída. Nada foi executado de
  verdade. Nada foi salvo. Nenhum dado sensível foi exibido."), sem jargão; o
  bloco técnico `DRY_RUN=true`/`REAL_*` fica sob "Status:" e os detalhes
  completos no `--json`.

### Security (MC22)
- CLI dry-run output remains redacted and emits only approved safe scalar
  fields: o prompt nunca é ecoado, o resultado do orquestrador nunca é
  serializado (sem `to_dict`/`repr`/`vars`/`asdict`), `conselho` continua
  roteado antes de `_paths()` e o harness/policy/vault/audit reais não são
  chamados. 15 testes novos (migração + UX + regressão). Suíte: 922 → 937.

### Not changed (MC22)
- Chat dry-run was not migrated yet (`chat_dry_run.py`/`amigavel.py`
  intocados); o helper `safe_output.py` não foi alterado.
- No real engine execution enabled.
- No PyPI publication; nenhuma tag ou release criada.

### Added (MC21)
- Added isolated Motor Council shared safe output/redaction helper
  (`src/nomos/council/safe_output.py`) for future CLI/chat dry-run
  unification: `CouncilSafeOutput` (frozen dataclass, 10 campos escalares
  seguros + `to_json_dict`) e as funções `build_safe_output`/
  `render_human_output`/`render_json_output`/`render_denied_output`/
  `render_gate_blocked_output`/`render_exception_output`, parametrizadas por
  `interface` (`cli`/`chat`).

### Security (MC21)
- Safe output helper emits only approved scalar fields and fails closed for
  invalid results: nunca serializa o resultado inteiro do orquestrador (sem
  `to_dict`/`repr`/`vars`/`asdict`), nunca emite prompt/content/engine_id/
  secret/token/api_key/trace/audit_envelope, e trava
  `dry_run=true`/`would_execute=false`/`would_write_audit=false` por
  construção. `interface`/`mode` inválidos ⇒ `ValueError`; resultado inválido
  ⇒ `SAFE_OUTPUT_INVALID_RESULT`. 36 testes novos (incl. AST). Suíte: 886 → 922.

### Not changed (MC21)
- CLI and chat dry-run commands were not migrated yet (`cli_dry_run.py`/
  `chat_dry_run.py`/`cli.py`/`amigavel.py` intocados).
- No real engine execution enabled; no runtime behavior changed.
- No PyPI publication; nenhuma tag ou release criada.

### Documentation (MC20)
- Added Motor Council shared output/redaction helper specification for future
  CLI/chat dry-run unification
  (`docs/architecture/MOTOR_COUNCIL_SHARED_OUTPUT_REDACTION_SPEC_v1.md`, 20
  seções): documenta a duplicação controlada entre `cli_dry_run.py` e
  `chat_dry_run.py` (incl. o achado de que a CLI tem 8 flags proibidas e o
  chat 10), os invariantes de segurança compartilhados, os dados proibidos e
  campos escalares permitidos, os contratos de saída por `interface`, um
  esboço de API (`CouncilSafeOutput` + `build_/render_*`, `API_SKETCH_ONLY`),
  o plano de migração MC21–MC24 e o plano de testes futuros. Ponteiros
  adicionados em INDEX, UX spec e chat dry-run spec.

### Not changed (MC20)
- No runtime behavior changed; nenhum helper implementado.
- No CLI/chat refactor performed (`cli_dry_run.py`/`chat_dry_run.py`
  intocados); suíte permanece em 886.
- No real engine execution enabled.
- No PyPI publication; nenhuma tag ou release criada.

### Documentation (MC19)
- Aligned README and Motor Council UX documentation with CLI **and** chat
  dry-run availability: README `## Motor Council` reescrita (ambas as
  superfícies têm `simular` em dry-run; o resto segue desabilitado), contagem
  de testes corrigida (778 → 884). `MOTOR_COUNCIL_INDEX_v1.md` ganhou o bloco
  "Estado de UX/superfícies" (MC14–MC18, `CLI_DRY_RUN_AVAILABLE=true`,
  `CHAT_DRY_RUN_AVAILABLE=true`, `REAL_EXECUTION_AVAILABLE=false`,
  `PRODUCTION_READY=false`) e nota sobre a duplicação controlada CLI/Chat.
  `MOTOR_COUNCIL_UX_SPEC_v1.md` ganhou "Current implementation status";
  `MOTOR_COUNCIL_CHAT_DRY_RUN_SPEC_v1.md` marcado como `IMPLEMENTATION=MC18_DONE`.

### Changed (MC19)
- Clarified Motor Council CLI/chat help text to reference the dry-run
  simulation commands: a linha do `/ajuda` do chat agora aponta para
  `/conselho simular` (dry-run), e um comentário interno desatualizado do
  `cli.py` foi corrigido. Nenhuma lógica de roteamento mudou; guardas de help
  adicionadas por teste.

### Not changed (MC19)
- No runtime behavior changed (`cli_dry_run.py`/`chat_dry_run.py`/orchestrator/
  harness/policy_gate/audit_envelope intocados).
- No real engine execution enabled; no CLI/Chat refactor.
- No PyPI publication; nenhuma tag ou release criada.

### Added (MC18-UX)
- Added `/conselho simular <texto>` as a redacted dry-run chat command backed
  by the Motor Council dry-run orchestrator (`CouncilOrchestratorDryRun`).
  Flags: `--modo rapido|balanceado|critico|paranoico` (paranoico ⇒ privado),
  `--privado`, `--json`, `--iniciante`, `--avancado`. Saída humana
  (`[NOMOS-MC-CHAT-DRY-RUN]`/`[NOMOS-MC-CHAT-GATE-BLOCKED]`) e JSON mínimo
  escalar. Novo módulo `src/nomos/council/chat_dry_run.py`; o ramo `/conselho`
  do loop de `amigavel.py` passou a rotear só `simular` para dry-run, mantendo
  os demais subcomandos desabilitados.

### Security (MC18-UX)
- Motor Council chat dry-run performs no real engine execution, persistence,
  real policy, real audit or real vault calls: `simular` chama apenas o
  orquestrador dry-run, nunca o harness real, e nunca constrói contexto de
  kernel. O prompt nunca é ecoado (humano/JSON/erro); flags proibidas
  (`--real`/`--enable`/`--cloud`/…) e desconhecidas falham fechado
  (`[NOMOS-MC-CHAT-DENIED]`). A saída é redigida à mão e **não serializa o
  resultado inteiro** do orquestrador (nunca `result.to_dict()`). Provado por
  33 testes novos (incl. integração pelo loop real e AST). Suíte: 851 → 884.

### Documentation (MC17-UX)
- Added Motor Council chat dry-run command specification for future
  `/conselho simular` (`docs/architecture/MOTOR_COUNCIL_CHAT_DRY_RUN_SPEC_v1.md`,
  20 seções): estado atual, contratos de entrada/saída, privacidade/redaction,
  flags proibidas, failure modes, integração com `CouncilOrchestratorDryRun` e
  `amigavel.py`, JSON futuro montado à mão (proibido `result.to_dict()`), plano
  de testes futuros e fases MC18-UX+. Ponteiro adicionado em
  `MOTOR_COUNCIL_UX_SPEC_v1.md`.

### Not changed (MC17-UX)
- No functional chat dry-run command enabled (`/conselho` segue desabilitado).
- No real engine execution enabled.
- No code/test/workflow changed; suíte permanece em 851.
- No PyPI publication; nenhuma tag ou release criada.

### Added (MC16-UX)
- Added disabled Motor Council chat command skeleton for the future
  `/conselho` UX. Aparece no `/ajuda` do chat amigável, mas nasce fail-closed:
  qualquer uso (`/conselho`, `/conselho simular ...`, etc.) devolve
  `[NOMOS-MC-CHAT-DISABLED]` + `CHAT_ENABLED=false` sem processar/ecoar o texto
  do usuário. Novo módulo puro `src/nomos/council/chat_disabled.py`
  (`handle_disabled_chat_command`, constante literal
  `MOTOR_COUNCIL_CHAT_ENABLED = False`); ramo `/conselho` no loop de
  `amigavel.py` delega ao handler.

### Security (MC16-UX)
- Motor Council chat remains fail-closed: no real engine execution, no
  persistence, no real policy/audit/vault calls, no orchestrator/harness call,
  no prompt echo, no env enable. Mensagens não relacionadas devolvem `None`.
  Provado por 23 testes novos (incl. integração pelo loop real e AST de
  pureza). Suíte: 828 → 851.

### Added (MC15-UX)
- Added `nomos conselho simular "texto"` as a redacted dry-run command backed
  by the Motor Council dry-run orchestrator (`CouncilOrchestratorDryRun`).
  Flags: `--modo rapido|balanceado|critico|paranoico` (paranoico ⇒ privado),
  `--privado`, `--json`, `--iniciante`, `--avancado`. Saída humana
  (`[NOMOS-MC-DRY-RUN]`/`[NOMOS-MC-GATE-BLOCKED]`) e JSON mínimo/redigido
  (`dry_run/allowed/blocked/would_execute/would_write_audit/private_mode/
  persist_allowed/failure_code`). Novo módulo `src/nomos/council/cli_dry_run.py`;
  o roteador de `conselho` em `cli.py` libera só `simular`, mantendo os demais
  subcomandos desabilitados.

### Security (MC15-UX)
- The Motor Council CLI still performs no real engine execution, persistence,
  real policy, real audit or real vault calls: `simular` chama apenas o
  orquestrador dry-run, nunca o harness real, e o roteamento acontece antes de
  `_paths()` (Vault/Policy/Audit não são construídos). O prompt nunca é ecoado
  (humano/JSON/erro); flags proibidas (`--real`/`--enable`/`--cloud`/…) e
  desconhecidas falham fechado (`[NOMOS-MC-CLI-DENIED]`). Provado por 29 testes
  novos (incl. AST de pureza). Suíte: 799 → 828.

### Added (MC14-UX)
- Added disabled Motor Council CLI skeleton for the future `nomos conselho`
  UX. O comando aparece no `nomos --help` ("pré-release, ainda DESABILITADO"),
  mas nasce fail-closed: qualquer uso devolve `[NOMOS-MC-CLI-DISABLED]` +
  `CLI_ENABLED=false` e não interpreta subcomando/prompt/flags. Novo módulo
  puro `src/nomos/council/cli_disabled.py` (constante literal
  `MOTOR_COUNCIL_CLI_ENABLED = False`, sem API de habilitação); `cli.py`
  curto-circuita `conselho` antes do argparse e de `_paths()`.

### Security (MC14-UX)
- Motor Council CLI remains fail-closed: no real engine execution, no
  persistence, no real policy/audit/vault calls, no orchestrator/harness call,
  no prompt echo, no env/flag bypass. Provado por 21 testes novos (incl. AST
  de pureza do módulo). Suíte: 778 → 799.

### Adicionado
- Índice técnico do Motor Council (`docs/architecture/MOTOR_COUNCIL_INDEX_v1.md`)
  consolidando as fases MC0–MC9: mapa de fases, mapa de arquitetura, arquivos
  criados, garantias de segurança/dry-run/modo privado/gate/audit, o
  travamento do harness de execução real, resumo da UX spec, progressão de
  testes (520 → 778), evidência de CI, quirks conhecidos do sandbox,
  não-escopo, riscos remanescentes e um checklist de prontidão para RC4.
- Notas de release em rascunho para `v1.3.0rc4` — Motor Council Dry-run
  (`docs/missions/RELEASE_NOTES_v1.3.0rc4_MOTOR_COUNCIL_DRY_RUN.md`).
- Rascunho de corpo de GitHub Release para `v1.3.0rc4`
  (`docs/missions/GITHUB_RELEASE_v1.3.0rc4_MOTOR_COUNCIL_DRY_RUN.md`).
- Fase MC11-RC4: validação completa de baseline, ancestry e conteúdo dos
  rascunhos RC4 antes de tag; reconciliação da numeração de fases futuras —
  `MC11-RC4` passa a ser a trilha de release engineering (tag/release/PyPI),
  e a trilha de UX prevista pelo MC9 foi renumerada de MC11–MC16 para
  `MC12-UX`–`MC17-UX` em `MOTOR_COUNCIL_UX_SPEC_v1.md`.

### Achado (MC11-RC4)
- `.github/workflows/release.yml` publica um GitHub Release automaticamente
  em qualquer push de tag `v*`. Reportado ao usuário antes de qualquer push
  de tag (ver `docs/missions/MOTOR_COUNCIL_MC11_RC4_TAG_PREPARATION.md`,
  seção 8); a decisão explícita do usuário foi prosseguir com a tag e
  corrigir o release automático depois, em vez de segurá-la.

### Publicado (MC11-RC4, pós-decisão do usuário)
- Tag anotada `v1.3.0rc4-motor-council-dry-run` criada e enviada, apontando
  para o commit já validado com CI 17/17.
- O push da tag disparou `release.yml`, que publicou um GitHub Release
  automaticamente. Ele saiu inicialmente `prerelease=false` e marcado como
  "latest" (diferente do padrão dos 4 releases anteriores, todos
  `prerelease=true`); corrigido via API para `prerelease=true` /
  `make_latest=false` — sem criação, edição de conteúdo ou remoção manual,
  apenas correção das duas flags de um release que o workflow já havia
  criado sozinho. Corpo do release permanece o texto genérico do template;
  melhorá-lo fica para `MC12-RC4`, assim como ajustar `release.yml` para não
  precisar dessa correção pós-hoc na próxima tag.

### Fixed (MC12-RC4)
- Corrected RC4 GitHub Release metadata/body to publish as pre-release, not
  latest: título trocado de `v1.3.0rc4-motor-council-dry-run` (genérico) para
  `NOMOS v1.3.0rc4 — Motor Council Dry-run`, corpo trocado do texto padrão do
  workflow pelo conteúdo técnico de `docs/missions/
  GITHUB_RELEASE_v1.3.0rc4_MOTOR_COUNCIL_DRY_RUN.md` (postura de segurança,
  `PYTEST=778`/`CI=17/17`, itens incluídos/não incluídos, instalação).
  `prerelease=true`/`draft=false`/`make_latest=false` reconfirmados;
  `/releases/latest` continua 404.
- Hardened release workflow so future RC tags are not published as
  latest/final: `.github/workflows/release.yml` ganhou um step
  `Resolve release flags` que decide `prerelease`/`make_latest` a partir do
  nome da tag (`*rc*` ⇒ `prerelease=true`/`make_latest=false`), eliminando a
  necessidade de correção manual pós-publicação na próxima tag `v*rc*`.

### Not changed
- Nenhum código de runtime alterado (`src/**` intocado).
- Nenhum teste alterado (`tests/**` intocado); suíte permanece em 778.
- Nenhum comando CLI ou chat implementado.
- Nenhuma tag movida, recriada ou apagada; nenhuma publicação no PyPI.
- Nenhum asset binário novo anexado ao release existente.

### Documentation (MC13-RC4)
- Aligned public README/docs with RC4 Motor Council dry-run status: nova seção
  `## Motor Council` no `README.md` deixando explícito que o Council está em
  dry-run/pre-release (sem execução real, sem CLI/chat, sem nuvem/rede/
  subprocess, policy gate/audit só dry-run, modo privado força
  `persist_allowed=false`), apontando para o índice técnico e a UX spec.
  Contagem de testes no README corrigida de 494 (obsoleta) para 778, e a nota
  de maturidade agora marca o RC4 como pre-release.
- Added post-release verification notes for `v1.3.0rc4-motor-council-dry-run`
  (`docs/missions/MOTOR_COUNCIL_MC13_RC4_POST_RELEASE_VERIFICATION.md`) e um
  bloco "Estado pós-release" em `MOTOR_COUNCIL_INDEX_v1.md`
  (`RC4_RELEASE_PUBLISHED=true`, `RC4_PRERELEASE=true`, `RC4_LATEST=false`,
  `RELEASE_WORKFLOW_RC_GUARD=true`, `README_PUBLIC_ALIGNMENT=done`).

### Not changed (MC13-RC4)
- No runtime code changed (`src/**` intocado).
- No tests changed (`tests/**` intocado); suíte permanece em 778.
- No CLI/chat command implemented.
- No PyPI publication; nenhuma tag criada/movida/apagada; nenhum workflow
  alterado nesta fase.

## [1.3.0rc16] — 2026-07-04 (Motor Council — Fase MC8: orquestrador dry-run)

### Adicionado (interno, sem wiring de runtime)
- `nomos.council.orchestrator`: orquestrador **SPEC/DRY-RUN** que compõe, em
  memória, provider local (MC3/MC4) → simulador offline (MC2) → policy gate
  (MC6) → audit envelope (MC7) num único fluxo. `CouncilOrchestratorDryRun`,
  `CouncilOrchestrationInput/Result/Step/Trace/Failure`,
  `CouncilOrchestrationStepName`, `OrchestrationFailureCode`.
- Trace metadata-only prova a ordem determinística: `INPUT_VALIDATED` →
  `LOCAL_PROVIDER_EVALUATED` → `CANDIDATES_CREATED` → `SIMULATOR_RAN` →
  `POLICY_GATE_EVALUATED` → `FINAL_ENVELOPE_CREATED` → `AUDIT_ENVELOPE_CREATED`
  → `ORCHESTRATION_COMPLETED`/`ORCHESTRATION_BLOCKED` — o gate **sempre** antes
  do envelope final, o audit envelope **sempre** depois do gate, mesmo quando
  bloqueado. `private_mode=true` propaga `persist_allowed=false` para o
  envelope final e para todos os envelopes de auditoria.
- `dry_run=true`, `would_execute=false`, `would_write_audit=false` SEMPRE.
  Fail-closed de ponta a ponta: A6, dado sensível, sem candidatos elegíveis ou
  exceção de um componente plugável (provider/simulador/gate/audit builder)
  todos resultam em `allowed=false`, com trace completo e conteúdo nulo no
  envelope final. Códigos `ORCH_*` (9) cobrindo entrada inválida, provider,
  simulador, gate, audit envelope e invariantes de modo privado/dry-run.
- **O módulo não importa o harness de execução real (MC5)** — nenhum caminho,
  direto ou indireto, para execução real. Provider padrão usa o adaptador
  dry-run (MC4). **Sem motor real, Ollama, subprocess, HTTP, cloud, SDK, FS,
  env, tempo ou random; sem policy/vault/audit/approval reais.**
- 54 testes novos (contratos, comportamentos obrigatórios, ordem do trace,
  fail-closed por exceção plugável, invariantes de modo privado/dry-run,
  segurança AST). Suíte: 778.

## [1.3.0rc15] — 2026-07-04 (Motor Council — Fase MC7: audit envelope privado)

### Adicionado (interno, sem wiring de runtime)
- `nomos.council.audit_envelope`: envelope de auditoria SPEC/DRY-RUN.
  `CouncilAuditEnvelope/Builder`, `CouncilAuditEventType`,
  `CouncilAuditRedactionProfile`, `CouncilAuditDryRunResult`,
  `CouncilAuditEnvelopeFailure`, e `run_offline_council_with_audit_envelope`.
- `dry_run=true` e `would_write_audit=false` SEMPRE (sem escrita real no audit,
  sem disco). **`private_mode=true` ⇒ `persist_allowed=false`** em todos os
  envelopes, com redação máxima. Metadata é **só contagens/failure_code**;
  chaves/valores sensíveis (prompt/content/api_key/token/bearer/engine_id…) são
  bloqueados (`AUDIT_ENVELOPE_SENSITIVE_METADATA`) e nunca aparecem em to_dict/
  to_json/repr/warnings. Envelope com escrita real ou não-redigido ⇒ negado.
- **Sem audit/vault/policy/approval reais, sem motor, HTTP, subprocess, cloud,
  SDK, FS, env, tempo ou random.** Determinístico.
- 31 testes novos (redação, private, no-write, metadata sensível, builder nunca
  inclui conteúdo, integração, segurança AST). Suíte: 724.

## [1.3.0rc14] — 2026-07-04 (Motor Council — Fase MC6: policy gate dry-run)

### Adicionado (interno, sem wiring de runtime)
- `nomos.council.policy_gate`: integração SPEC/DRY-RUN com o Policy Gate A0–A6.
  `CouncilPolicyGateDryRun`, `CouncilGateRequest/Decision`,
  `FinalResponseEnvelope`, `CouncilGateFailure`/`GateFailureCode`,
  `CouncilGateRisk`, e `run_offline_council_with_policy_gate`.
- Toda resposta final simulada só é liberada se o gate devolver `allowed=true`.
  `dry_run=true`, `would_call_real_policy=false`, `would_request_approval=false`
  SEMPRE. Fail-closed determinístico: arbiter bloqueado, conteúdo vazio, A6,
  aprovação humana exigida, dado sensível e A3+ ⇒ negado; A0/A1/A2 liberados.
  Gate negado ⇒ envelope sem conteúdo; modo privado ⇒ `persist_allowed=false`.
- **Sem policy/approval/vault/audit reais, sem motor, HTTP, subprocess, cloud,
  SDK, FS, env, tempo ou random**; conteúdo final nunca vaza (repr/serialização).
- 30 testes novos (decisões, envelope, integração, segurança AST). Suíte: 693.

## [1.3.0rc13] — 2026-07-04 (Motor Council — Fase MC5: harness fail-closed)

### Adicionado (interno, sem wiring de runtime)
- `nomos.council.local_harness`: harness de execução local **FAIL-CLOSED**.
  Constante literal `REAL_LOCAL_ENGINE_EXECUTION_ENABLED = False` (não vem de
  env/config/argumento; sem API de enable/activate/unlock/set_enabled).
  `LocalExecutionHarness`, `LocalExecutionRequest/Result/AttemptRecord`,
  `LocalExecutionFailure`, `ExecutionFailureCode`.
- Qualquer tentativa de execução real ⇒ `executed=false` e `candidate=null`
  SEMPRE; código `REAL_EXECUTION_DISABLED` (ou `REAL_EXECUTION_ENGINE_NOT_LOCAL`
  para motor não-local). Modo privado ⇒ `persist_allowed=false`. Env não ativa
  (módulo não lê variáveis do sistema). O dry-run do MC4 continua intacto.
- **Sem motor real, Ollama, subprocess, HTTP, cloud, SDK remoto, FS, env, tempo
  ou random**; prompt nunca é armazenado (só `prompt_chars`) nem vaza.
- 26 testes novos (fail-closed, flag literal via AST, env-não-ativa, sem API de
  ativação, dry-run intacto, provas de pureza). Suíte: 663.

## [1.3.0rc12] — 2026-07-04 (Motor Council — Fase MC4: adaptador local dry-run)

### Adicionado (interno, sem wiring de runtime)
- `nomos.council.local_adapter`: contrato de adaptador de motor local em
  **SPEC/DRY-RUN** — `LocalEngineAdapter` (Protocol), `DryRunLocalEngineAdapter`,
  `LocalEngineExecutionPlan`, `LocalEngineDryRunResult`,
  `LocalEngineIsolationProfile`, `LocalEngineAdapterPolicy`,
  `DryRunAdapterCandidateProvider`, `LocalAdapterFailure` e `AdapterFailureCode`.
- **Não executa nada**: `would_execute=false` e `dry_run=true` SEMPRE. Perfil de
  isolamento nega tudo por padrão (network/subprocess/filesystem/env/cloud/
  loopback) e qualquer permissão ⇒ erro. Política `dry_run_only`/`local_only`
  obrigatórias. Motor não-local/cloud/rede/prompt-grande ⇒ bloqueado com código
  próprio (ADAPTER_*), mapeado a CouncilFailureCode no provider.
- **Sem motor real, Ollama, subprocess, HTTP, cloud, SDK remoto, FS, env, tempo
  ou random**; juízes/árbitro/gate seguem simulados. Prompt nunca entra no plano,
  resultado, warnings, conteúdo ou repr. Determinístico.
- 29 testes novos (contratos + dry-run + provider + segurança AST, incl. ausência
  de mutação global). Suíte: 637.

## [1.3.0rc11] — 2026-07-04 (Motor Council — Fase MC3: contrato de provedor local)

### Adicionado (interno, sem wiring de runtime)
- `nomos.council.local_provider`: contrato refinado de provedor de candidatos
  LOCAIS — `LocalCandidateProvider` (Protocol), `DeterministicLocalCandidate
  Provider`, `LocalEngineDescriptor`, `LocalCandidateRequest/Result`,
  `LocalProviderFailure`, e `run_offline_council_with_local_provider`.
- Códigos de falha distintos por causa: cloud/rede ⇒
  `CLOUD_BLOCKED_BY_LOCAL_LOCK`; dado sensível sem motor capaz ⇒
  `SENSITIVE_DATA_CLOUD_DENIED`; sem motor local ⇒ `NO_ELIGIBLE_LOCAL_ENGINE`.
  `supports_sensitive_data` bloqueia prompts sensíveis em motor incapaz.
- **Sem motor real, sem Ollama/cloud/rede/SDK remoto, sem FS/env, sem tempo/
  random, sem policy/vault/audit reais, sem persistência, sem CLI/chat.** Juízes/
  árbitro/gate seguem simulados (MC2). Prompt nunca vaza (repr/to_dict/resultado).
- 31 testes novos (contratos + segurança, incl. prova AST de pureza e
  determinismo). Suíte: 608.

### Alterado
- Consolidação: `local_engine.py` (MC3 anterior) foi **superseded** por
  `local_provider.py` (contrato desta fase, com códigos de falha distintos) e
  removido, junto de seus testes, para não manter dois provedores paralelos.

## [1.3.0rc10] — 2026-07-04 (Motor Council — Fase MC3: integração de motor local)

### Adicionado (interno, sem wiring de runtime)
- `nomos.council.local_engine`: camada por CONTRATO que troca só a origem dos
  candidatos — `LocalCandidateProvider` (Protocol) + `DeterministicLocalCandidate
  Provider` (fake determinístico), `LocalEngineDescriptor/Eligibility/Failure`,
  `LocalCandidateRequest/Result`, e `run_offline_council_with_local_candidates`.
- Motores exigem prefixo `local:`; um motor com cloud/rede/não-local é
  **inelegível** (nunca usado). **Sem cloud, sem rede, sem SDK remoto
  (OpenAI/Anthropic/Ollama), sem FS, sem env, sem policy/vault/audit reais, sem
  persistência, sem CLI/chat.** Juízes/árbitro/gate continuam simulados (MC2).
- `simulator`: refatorado para expor `run_with_candidates(...)` (reutilizado
  pela integração local); `run()` delega — comportamento MC2 idêntico.
- Fail-closed: sem motor local elegível ⇒ `NO_ELIGIBLE_LOCAL_ENGINE` bloqueado;
  gate simulado negado ⇒ bloqueado. Invariantes MC1 preservadas (paranoid/
  sensível/privado). Prompt nunca vaza no repr/serialização.
- 29 testes novos (contratos + segurança, incl. prova AST de pureza). Suíte: 606.

## [1.3.0rc9] — 2026-07-04 (Motor Council — Fase MC2: simulador offline)

### Adicionado (interno, sem wiring de runtime)
- `nomos.council.simulator`: simulador OFFLINE determinístico do pipeline do
  Council (Risk → Policy → Candidatos(fixtures) → Reviews(fixtures) →
  Divergência → Árbitro → Gate simulado → Audit), puro sobre os modelos MC1.
  `OfflineCouncilSimulator/Input/Result`, `SimulatedEngineFixture/JudgeFixture/
  PolicyGateResult`.
- **Sem motor real, sem LLM, sem rede, sem persistência, sem policy/audit/vault
  reais, sem CLI/chat.** Fixtures obrigam prefixo `fixture:`. Failure codes
  determinísticos (sem candidatos, gate negado, divergência alta, alerta crítico,
  autojulgamento/juízes insuficientes, conselho desligado, falha de motor).
  Invariantes MC1 preservadas (paranoid→local-only, sensível→sem cloud,
  privado→sem persistência). Prompt nunca vaza em repr/serialização.
- 26 testes novos (contratos + segurança, incluindo prova AST de que o módulo
  não importa rede/subprocess/threading/asyncio/motor e não toca FS/policy/vault/
  audit). Suíte: 577. Determinismo provado (mesma entrada ⇒ mesma saída).

## [1.3.0rc8] — 2026-07-04 (Motor Council — Fase MC1: modelos de dados)

### Adicionado (interno, sem wiring de runtime)
- `nomos.council.models`: modelos de dados puros do Motor Council (stdlib-only),
  conforme docs/architecture/MOTOR_COUNCIL_SPEC_v1.md. 12 modelos (session,
  policy, risk, candidate, blind_review, judge_score, arbiter_decision,
  disagreement, audit_record + enums de modo/risco/confiança/divergência/falha).
- Invariantes de segurança por construção (fail-closed): paranoid⇒local-only,
  local_only⇒sem cloud, private_mode⇒sem persistência, dado sensível⇒cloud negada.
  `repr` de modelos com texto do usuário não vaza conteúdo; anonimização remove
  autoria; autojulgamento é detectável; scores 0–5 validados.
- **Sem execução de motor, sem I/O, sem rede, sem persistência, sem CLI/chat.**
  31 testes novos (contratos + segurança, incluindo prova de que o módulo não
  importa rede nem motor/LLM). Suíte: 551.

## [1.3.0rc7] — 2026-07-04 (hardening do audit log — âncora HMAC no cofre)

### Adicionado
- **Âncora HMAC da cadeia de auditoria** (`kernel/audit_anchor.py`), mitigando a
  lacuna divulgada na auditoria: a hash-chain (sem chave) não detectava
  **truncamento de cauda** nem reescrita completa por quem tem escrita.
  - HMAC-SHA256 sobre {schema, entries_count, chain_tip, log_id, created_at};
    a **chave vive no cofre** (Argon2id) — nunca em claro, nunca logada, nunca
    impressa em erro; acessada fail-closed. Não é defesa-teatro: quem não tem a
    passphrase não forja a âncora, mesmo com escrita no NOMOS_HOME.
  - `nomos logs verify` reporta o estado: LEGACY_UNANCHORED (WARN),
    ANCHORED_VALID (PASS), ANCHORED_INVALID / TAIL_TRUNCATED / ANCHOR_MISSING /
    CHAIN_CORRUPTED (FAIL), ANCHOR_UNVERIFIED (WARN, sem passphrase).
    `--cofre` valida o HMAC.
  - `nomos logs anchor` cria/atualiza a âncora (gate A3 + passphrase),
    idempotente; avisa que logs antigos não provam ausência de truncamento
    anterior; audita `audit.ancorado` (só metadados).
- `AuditLog.estado()` e `AuditLog.tip_em(n)` para a âncora.

### Segurança
- Logs legados sem âncora nunca passam em silêncio (WARN, não PASS). Cadeia já
  corrompida não é ancorada (não mascara corrupção pré-existente).

## [1.3.0rc6] — 2026-07-04 (correção de CI — gate POSIX no Windows)

### Corrigido
- **Último teste vermelho no Windows**: `test_vault2.py::test_lockout_arquivo_0600`
  verificava modo de arquivo `0600` (POSIX), que o Windows não aplica. Recebeu o
  mesmo gate `skipif(os.name=="nt")` já usado nos outros testes de permissão
  (vault, chaves, memory, skill_signing). Depois do rc5, as falhas do Windows
  caíram de 35 para 1; esta fecha a última.

## [1.3.0rc5] — 2026-07-04 (correção de CI — fins-de-linha no Windows)

### Corrigido
- **CI vermelho no Windows** (35 testes, todos "checksum divergente em main.py"):
  causa-raiz de fim-de-linha. Skills declaram sha256 dos próprios arquivos e a
  verificação lê bytes crus; no Windows, `write_text` grava CRLF, mudando os
  bytes e quebrando a integridade. Correções:
  - `.gitattributes` força LF (`* text=auto eol=lf`) — mantém as skills oficiais
    versionadas válidas no checkout Windows;
  - `skill_sdk.criar_skill` grava main.py/skill.json/README com `newline="\n"`
    (skill criada no Windows agora passa a própria verificação);
  - testes que geram main.py em runtime gravam LF determinístico.
  Provado localmente simulando CRLF (diverge) vs LF (confere). Sem afrouxar a
  verificação de integridade — os bytes seguem exatos, só determinísticos.

## [1.3.0rc4] — 2026-07-04 (F5+F6 do plano de validação)

### Adicionado
- **Rotina dry-run** (F5/ISSUE-023): `nomos rotinas executar --simular` mostra
  o que faria SEM executar nem marcar como feito; auditoria registra
  `rotina.simulada`. `prever_acao` descreve cada ação.
- **Smoke pós-instalação no CI** (F6/ISSUE-024): job que constrói o wheel,
  instala em ambiente limpo nos 3 SOs e roda `nomos doutor` como relatório de
  saúde.

### Corrigido
- **Agentes oficiais não vinham no wheel** (defeito pego pelo smoke da F6):
  movidos de `examples/` para `src/nomos/agents/oficiais/` e empacotados;
  `nomos agentes listar` agora funciona na instalação por wheel.

## [1.3.0rc3] — 2026-07-04 (F4 do plano de validação — UX)

### Adicionado
- **Memória tipada** (ISSUE-019): `remember_typed` com tipo (fato/preferência/
  tarefa/projeto/contato/decisão/regra), fonte e confiança; migração automática
  de bancos antigos sem perder nada; detecção de contradições.
- **Memórias candidatas** (ISSUE-020): "você quer que eu lembre disso?" —
  candidata não vira memória sem aprovação (propor/aprovar/descartar).
- **Erro humano** (ISSUE-021): `erros.explicar(codigo)` dá uma frase clara + o
  próximo passo para cada `[NOMOS-Exx]`; teste garante uma explicação por código.
- **Modo iniciante** (ISSUE-022): menu principal esconde o avançado; alterna
  com "avancado"/"iniciante".

## [1.3.0rc2] — 2026-07-04 (F3 do plano de validação — agentes locais)

### Adicionado
- **Agentes locais governados** (ISSUE 013–018), lacuna confirmada na
  validação. Regra inegociável **provada por teste**: agente NÃO é atalho para
  burlar política.
  - `AgentManifest`: ferramentas de uma **allowlist fechada**; o manifesto não
    pode declarar risco menor do que suas ferramentas exigem (fail-closed).
  - `AgentToolBoundary`: agente só acessa ferramenta do seu manifesto e toda
    ação passa pelo MESMO `policy.gate` A0–A6 do kernel — sem gate novo, sem
    herança de permissão entre agentes.
  - `AgentRegistry`: instalar/listar/ativar + sugestão por keyword (só do texto
    digitado).
  - **3 agentes oficiais** (examples/agents): pesquisador-local (A0),
    programador (A1), seguranca (A0), validados por teste.
- Comandos: `nomos agentes listar|info|ativar|desativar|diagnostico`.
- Auditoria por agente: uso e negação de ferramenta.

## [1.3.0rc1] — 2026-07-04 (F2 do plano de validação — histórico de conversas)

### Adicionado
- **Histórico de conversas** (ISSUE 006–012), lacuna confirmada na validação:
  conversas viram cidadãs de primeira classe (SQLite local 0600), com título e
  tags gerados localmente, busca híbrida (palavra-chave + significado), fixar,
  "não usar como memória", reabrir e continuar com contexto.
- **Modo privado/efêmero** (`/privado`): a conversa roda em store `:memory:` e
  **não toca o disco** — provado por teste que inspeciona o FS.
- **Retenção** configurável: conversas não fixadas expiram após N dias, só
  localmente, com aviso; fixadas nunca expiram.
- **Export/import cifrado** (Fernet + PBKDF2 600k): `nomos conversas
  exportar/importar`; senha errada/adulterado ⇒ nada importado.
- Comandos: `nomos conversas listar|abrir|buscar|esquecer|fixar|exportar|
  importar|retencao`. Chat: `/conversas /continuar <id> /fixar /privado`.

### Segurança
- Conversa privada não persiste; logs guardam só metadados (id/contagem),
  nunca texto; export exige aprovação (senha via TTY ou NOMOS_BACKUP_SENHA).

## [1.2.0rc2] — 2026-07-04 (F1 do plano de validação — endurecimento)

### Segurança
- **Anti prompt-injection** (ISSUE-001): conteúdo recuperado (memória/RAG) é
  ENVELOPADO com preâmbulo "isto é DADO, não instrução" e delimitadores únicos
  por chamada; marcadores embutidos no conteúdo são neutralizados. A oferta de
  skill por intenção passa a considerar SOMENTE o texto digitado pelo usuário
  (`prompt_guard.texto_confiavel`), nunca o conteúdo recuperado. 5 testes.
- **XSS do painel** (ISSUE-005): teste garante que nome com `<script>` sai
  escapado.

### Higiene / qualidade
- `.coverage` removido do versionamento e ignorado (ISSUE-002).
- Contagem de comandos corrigida (27→25) na documentação (ISSUE-003).
- **mypy** informativo no CI sobre o kernel, não bloqueante (ISSUE-004).

## [1.2.0rc1] — 2026-07-04 (fase v1.2 do ROADMAP_2)

### Adicionado
- **O agente age na conversa**: skills instaladas declaram `keywords` no
  manifesto e o chat OFERECE a skill certa quando a intenção bate — "posso
  usar a skill 'X' para isso? (sim/não)". "sim" executa pelo gate de sempre e
  o JSON vira resposta legível; "não" segue a conversa normal. Heurística
  local e determinística: nenhuma IA decide, skills desativadas/quebradas
  nunca são oferecidas.
- **`/skills usar <nome> [json]`** no chat: invocação explícita com o mesmo
  gate; JSON inválido tem erro claro.
- **Skill oficial nº 4 — `busca-arquivos`** (A0, só leitura): "onde está o
  contrato?" procura por nome e conteúdo com limites de varredura.
- **Auditoria da cadeia**: evento `skill.conversa` (nome, origem
  oferta/explicito, rc) — metadados, nunca o conteúdo do resultado.

## [1.1.0rc1] — 2026-07-04 (fase v1.1 do ROADMAP_2)

### Adicionado
- **Streaming de tokens**: a resposta aparece enquanto o motor local gera
  (Ollama via NDJSON e cérebro embutido via llama.cpp stream). Backend sem
  stream faz fallback honesto (resposta completa de uma vez); Ctrl+C no meio
  interrompe limpo e a resposta parcial NÃO vira memória. Nuvem continua
  não-stream (opt-in como sempre).
- **RAG local**: antes de responder, a busca híbrida puxa até 3 memórias
  relevantes para o contexto — com rodapé honesto "(usei N lembrança(s)
  suas)" no chat e no `nomos chat`. Instrução explícita ao motor: usar só se
  fizer sentido, nunca inventar além delas.
- **`/contexto`**: mostra EXATAMENTE o que foi enviado ao motor na última
  resposta, com segredos redigidos (padrões sk-/AKIA/JWT viram [REDIGIDO]).
- **Janela adaptativa**: conversa acima de 8k chars encolhe — o miolo antigo
  vira um resumo heurístico LOCAL (determinístico, sem custo de inferência);
  as mensagens recentes seguem intactas.

## [1.0.0rc2] — 2026-07-03 (fase v1.0.1 do ROADMAP_2)

### Adicionado
- **Boot instantâneo**: módulos pesados (cryptography/argon2/cognição) só
  carregam no comando que os usa — `nomos --version` caiu de 53 módulos
  pesados no boot para zero (~40 ms); teste determinístico garante que não
  regride.
- **`nomos doutor --consertar`**: aplica correções SEGURAS (pastas ausentes;
  localidade/policy/rotinas/estado corrompidos → recriados com padrão seguro,
  original preservado como `.corrompido`) com confirmação digitada
  ("CONSERTAR"); sem TTY lista e nega. Nada destrutivo, tudo auditado.
- **`nomos backup criar|restaurar|inspecionar`**: o NOMOS inteiro num arquivo
  cifrado (tar → Fernet + PBKDF2 600k; exclui `modelos/` re-baixáveis, com
  aviso). Restaurar em home com conteúdo exige "RESTAURAR" em TTY e preserva
  o atual em `.antes-restauro-<ts>/`; senha errada/adulterado ⇒ nada muda;
  caminhos do tar validados contra escape.
- **Códigos de erro pesquisáveis** `[NOMOS-Exx]` nos caminhos de erro
  principais + docs/ERROS.md; teste garante que todo código usado está
  catalogado E documentado.
- **Motor sem compilador**: `cerebro instalar` usa `--prefer-binary` e, ao
  falhar, explica o caminho (ferramentas de build ou Ollama).

## [1.0.0rc1] — 2026-07-03

### Adicionado
- **Modelo de ameaças formal** (docs/THREAT_MODEL.md): STRIDE → mitigação →
  teste que prova; riscos residuais declarados, não mascarados.
- **Cobertura no CI**: job dedicado com `--cov-fail-under=80`. Medição atual:
  kernel ≥92% (policy e localidade 100%), geral 83%.
- **Empacotamento**: templates prontos de Homebrew (`packaging/homebrew`) e
  winget (`packaging/winget`) para preencher na release final.

### Pendente para o 1.0.0 final (fora do código)
- Auditoria de segurança independente do kernel; CI verde no GitHub
  (pós-push); release pública; publicação nas lojas. Ver
  docs/missions/NOMOS_ROADMAP_EXECUTION_REPORT.md.

## [0.18.0] — 2026-07-03

### Adicionado
- **O roteador aprende com você, localmente**: `/bem` e `/mal` no chat (ou
  `nomos motores feedback <motor> bom|ruim`) registram votos por motor em
  `feedback.json` (0600). Motor mal avaliado é rebaixado na escolha; a
  confiança da decisão reflete sua experiência. Zero telemetria — o voto
  nunca sai da máquina, e a razão da escolha explica o efeito.
- **Visão no chat** (`/ver <imagem>`): descreve imagens com modelo de visão
  LOCAL (Ollama/llava, loopback apenas — host externo é recusado por
  projeto). Sem modelo: instrução honesta de 1 linha.
- **Catálogo do cérebro estendido**: nomos-pro (Qwen2.5 7B) e nomos-max
  (Llama 3.1 8B) para máquinas com 16+ GB — mesmo fluxo opt-in de download.
- **Pipeline paralelo** (`run_parallel`): etapas independentes em threads,
  com TODOS os gates decididos antes (uma negação cancela o lote inteiro
  antes de qualquer execução).

## [0.17.0] — 2026-07-03

### Adicionado
- **Painel local** (`nomos painel`): o NOMOS inteiro numa página do navegador
  — STATUS GERAL, check-up, motores por modalidade, skills, rotinas e os
  últimos eventos da auditoria. **Somente leitura** (POST ⇒ 405): agir
  continua no terminal e no painel de aprovações, com gate.
- Mesmas garantias do painel de aprovações: bind exclusivo em 127.0.0.1
  (outro host ⇒ recusa), URL com segmento secreto (sem ele ⇒ 404), HTML
  autossuficiente sem assets externos, erro interno nunca vaza detalhes.

## [0.16.0] — 2026-07-03

### Adicionado
- **Rotinas locais** (`nomos rotinas`): criar (com aprovação humana no gate
  A1 — rotina roda sozinha depois, então nasce só com seu sim), listar,
  pausar/retomar, remover, executar. Ações permitidas: registro fixo seguro
  (briefing, doutor, consolidar-memoria) ou `skill:<nome>` — skills que pedem
  aprovação NÃO rodam em rotina (fail-closed, por design).
- **Briefing do dia** (`nomos rotinas briefing`): tarefas e datas anotadas,
  rotinas configuradas e o próximo passo do doutor — 100% local.
- **`nomos rotinas agendar`**: mostra a linha de crontab/Agendador para VOCÊ
  colar — o NOMOS nunca altera o agendador do sistema sozinho.
- Cada rotina roda no máximo 1x por dia; arquivo corrompido ⇒ nada roda.

## [0.15.0] — 2026-07-03

### Adicionado
- **SDK de skills**: `nomos skills criar <nome>` gera esqueleto completo e
  válido (main.py com I/O JSON, skill.json v2 com checksums, README com
  assinatura e publicação). Nome validado; nunca sobrescreve.
- **I/O estruturado**: `nomos skills rodar <nome> --args '<json>'` — os
  argumentos chegam à skill por arquivo efêmero (limpo após a execução) e a
  resposta JSON é interpretável (`executar_json`).
- **Catálogo assinado**: catálogo local pode ser assinado (ed25519) por um
  publicador do trust store; assinatura inválida descarta o catálogo INTEIRO
  (fail-closed). `nomos skills atualizar` compara versões instaladas com o
  catálogo e informa — instalar continua manual, com gate.
- **3 skills oficiais de exemplo** em `examples/skills/` (organizador,
  lembrete, sistema-info): todas A0/risco baixo, validadas por teste.

## [0.14.0] — 2026-07-03

### Adicionado
- **Busca híbrida** (`memory search` e `/memoria buscar`): palavras-chave
  (comportamento clássico) + similaridade por significado via `semantica.py`
  — hashing local de n-gramas, zero dependência, zero rede, determinístico.
  Stopwords não dominam mais a fase de palavra-chave.
- **Backup cifrado de memórias**: `nomos memory exportar/importar <arquivo>`
  (Fernet + PBKDF2-SHA256 600k, sal por arquivo, 0600). Senha errada ou
  arquivo adulterado ⇒ nada importado; importar nunca apaga (deduplica).
- **Consolidação**: `nomos memory consolidar` extrai fatos, preferências e
  tarefas explícitas das conversas para notas duráveis (heurística local
  transparente, idempotente).

## [0.13.0] — 2026-07-03

### Adicionado
- **`nomos arquivo <caminho>`** e **`/arquivo`** no chat: lê txt/md/csv/json/
  log (e PDF com o extra opcional `nomos[arquivos]`), extrai pontos por
  heurística local transparente, resume com o motor local quando presente e
  — só com sua aprovação (A1) — salva o resumo ao lado do arquivo
  (`--salvar`). Sem cérebro: entrega os pontos e orienta, sem fingir resumo.
- **`/ouvir <áudio>`** no chat: transcreve com o whisper local, resume com o
  motor local e guarda na memória; sem whisper, orientação honesta em 1 linha.
- Limite de 5 MB por arquivo com mensagem clara; PDF escaneado (sem texto) é
  detectado e explicado.
- Pipeline de arquivos usa o EnginePipeline: etapas pela política, falha
  honesta, auditoria só com metadados e explicação final ("Nada saiu da sua
  máquina.").

## [0.12.0] — 2026-07-03

### Adicionado
- **CI no GitHub Actions**: pytest + ruff em ubuntu/macos/windows × Python
  3.10–3.13 (`.github/workflows/ci.yml`); badge no README.
- **Release automatizada** (`.github/workflows/release.yml`): em tag `v*`,
  valida a suíte, constrói wheel+sdist, gera `SHA256SUMS`, faz smoke do wheel
  e publica a release com os instaladores anexados.
- **Instaladores Windows**: `installer/install.ps1` e `uninstall.ps1` com os
  mesmos princípios fail-closed do Unix (checksum, backup, purge só com
  confirmação digitada). `install.sh` agora também instala a partir do wheel
  baixado da release (modo release) além do código-fonte (modo dev).
- **`nomos atualizar`**: checa a última versão publicada (api.github.com)
  apenas com o cadeado aberto + sua aprovação (gate A2); compara versões,
  mostra as novidades e o caminho manual. **Nunca baixa nem instala sozinho.**
- **Política anti-telemetria explícita** em docs/PRIVACIDADE.md, garantida
  por teste estático (allowlist de destinos externos justificada).
- Extra `dev` no pyproject (`pip install -e ".[dev]"`) e `[project.urls]`.

### Segurança
- Novo destino externo (`api.github.com`) adicionado à allowlist do teste
  fortaleza com justificativa — atrás do gate A2 e do cadeado só-local, como
  todos os demais. Nenhum caminho novo de autorização.

## [0.11.0] — 2026-07-03

### Adicionado
- **Menu principal amigável**: `nomos` (já configurado) abre menu numerado com
  10 opções; 1ª vez continua indo para o onboarding.
- **Skills amigáveis**: grupo `nomos skills` (menu, listar, instalar, remover,
  info, ativar, desativar, rodar, diagnostico) com status (ativa/inativa/
  quebrada/não confiável), risco (baixo/médio/alto), publicador e último uso.
- **Registry local de skills**: catálogo em `~/.nomos/registry/catalogo.json`
  (instalada × disponível × confiável × experimental).
- **Manifesto v2** de skill: description, entrypoint, risk_level (calculado se
  ausente — e nunca "afrouxável"), requires_approval, publisher,
  compatible_nomos_version, modalities, local_only_capable, cloud_required.
- **Execução governada de skills** (`nomos skills rodar`): só permissões
  declaradas, cada categoria pelo gate; rede cai no A2 (cadeado só-local);
  roda no sandbox.
- **Catálogo de motores v0.11** (12 modalidades: texto, codigo, raciocinio,
  resumo, memoria, voz_stt, voz_tts, imagem, visao, embeddings, ferramentas,
  roteamento) com custo, privacidade, velocidade, qualidade, chave e aprovação.
- **Roteador automático** (`engine_router`): local-first, honra dados
  sensíveis, nunca escolhe nuvem com só-local ligado, não inventa quando falta
  motor; produz `EngineRouteDecision` auditável. `nomos motores recomendar`,
  `auto on|off`, `testar`, `status`, `menu`, `diagnostico`.
- **Pipeline de motores** (`engine_pipeline`): etapas com política em cada
  passo, falha honesta na primeira negação, auditoria só de metadados,
  explicação simples ao usuário.
- **Doutor v0.11**: STATUS GERAL (PRONTO/PARCIAL/BLOQUEADO), checagem de
  Python, home, cofre, auditoria, localidade, cérebro, motores por modalidade,
  skills quebradas e **um** próximo passo recomendado.
- **Documentação real**: docs/INSTALL.md, MOTORES.md, SKILLS.md, ROTEADOR.md,
  PRIVACIDADE.md, USUARIO_INICIANTE.md + relatórios de missão em docs/missions/.
- **Testes**: novas suítes de skills/motores/roteador/pipeline/doutor e
  regressões de local-first, opt-in de nuvem e não-vazamento de segredo.

### Mantido (compatibilidade)
- Todos os comandos v0.10 funcionam sem mudança: `nomos skill ...`,
  `nomos motores`, `nomos motores usar`, `chat`, `vault`, `consent`, `run`,
  `memory`, `status`, `logs verify`, `doutor`, `cerebro`, `local`, `tema`,
  `chaves`, `approvals`, `start`.
- Políticas de segurança intactas: fail-closed, aprovação por TTY com palavra
  exata, redação de segredos, auditoria com cadeia de hash, sandbox isolado.

### Segurança
- Nenhum caminho novo de autorização: skills, roteador e pipeline usam o
  mesmo `gate()` de sempre. CI/non-interactive continua negando tudo sensível.

## [0.10.0] — anterior

- Kernel local-first (política A0–A6, cofre, auditoria, consentimento,
  localidade), cérebro leve embutido, cognição (router local→cloud opt-in,
  memória SQLite), skills assinadas, sandbox, UX simples em pt-BR (onboarding,
  chat amigável, doutor, tema, chaves). 246 testes.
