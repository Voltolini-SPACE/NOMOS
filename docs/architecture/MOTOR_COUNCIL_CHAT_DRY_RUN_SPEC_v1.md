# NOMOS Motor Council — Chat Dry-run Command Specification v1

## 1. Status

```text
SPEC_CREATED=true
IMPLEMENTATION=MC18_DONE
CHAT_DRY_RUN_ENABLED=true
REAL_ENGINE_EXECUTION=false
OUTPUT_MIGRATED_TO_SHARED_HELPER=MC23_DONE
```

> **Atualizado em MC23.** A saída/redação do `/conselho simular` foi migrada
> para o helper compartilhado `nomos.council.safe_output`
> (`build_safe_output` + `render_json_output`), igual ao CLI (MC22): o
> resultado do orquestrador nunca é serializado e o `--json` agora tem 10
> campos (`+interface`/`+mode`). A resposta humana ficou mais simples/amigável.
> As garantias de segurança abaixo continuam valendo e testadas. Ver
> `docs/missions/MOTOR_COUNCIL_MC23_CHAT_MIGRATION_SAFE_OUTPUT.md`.

> **Atualizado em MC19.** Esta spec nasceu SPEC-only (MC17-UX) e **foi
> implementada na Fase MC18-UX**: `/conselho simular <texto>` roda em dry-run
> no chat amigável, via `src/nomos/council/chat_dry_run.py`, chamando só o
> `CouncilOrchestratorDryRun`. As regras de segurança abaixo (não-eco de
> prompt, JSON escalar montado à mão sem `result.to_dict()`, sem harness/
> policy/audit/vault reais, sem persistência) **valem e foram testadas**. O
> que **continua bloqueado**: `/conselho` sem subcomando e os demais
> (`perguntar`, `revisar`, `status`, `modos`, `explicar`, `diagnostico`)
> seguem desabilitados/fail-closed (MC16-UX). `REAL_ENGINE_EXECUTION`
> permanece `false`.

Este documento descreve como o `/conselho simular` funciona no chat amigável
do NOMOS, espelhando o padrão seguro da CLI (`nomos conselho simular`, Fase
MC15-UX). Nas seções abaixo, o que estava marcado como "futuro" e foi entregue
na MC18-UX está indicado; o que segue futuro (ex.: aliases, aprovação humana)
permanece como desenho.

> **Unificação futura (MC20).** A saída/redação deste chat dry-run e a da CLI
> (`nomos conselho simular`) estão especificadas para unificação num helper
> compartilhado em
> `docs/architecture/MOTOR_COUNCIL_SHARED_OUTPUT_REDACTION_SPEC_v1.md`
> (SPEC-only; ainda não implementado).

## 2. Objective

Permitir, no futuro, que o usuário rode uma **simulação dry-run** do Motor
Council de dentro do chat amigável:

```text
/conselho simular <texto>
```

Essa simulação deve chamar **apenas** o `CouncilOrchestratorDryRun` (o
orquestrador puro, dry-run, já provado em MC8), imprimir um resultado
**redigido**, e nunca executar motor real, tocar policy/audit/vault reais, nem
persistir — exatamente como a CLI faz hoje. O chat é uma segunda superfície de
UX; esta spec garante que ela nasça com as mesmas garantias da primeira, sem
reabrir nenhum vetor de risco.

## 3. Current State

Hoje (após MC16-UX), no chat amigável (`src/nomos/simple/amigavel.py`):

```text
/conselho              = disabled / fail-closed
/conselho simular ...  = disabled / fail-closed
/conselho perguntar ...= disabled / fail-closed
/conselho revisar ...  = disabled / fail-closed
/conselho status       = disabled / fail-closed
/conselho modos        = disabled / fail-closed
```

Todos são atendidos pelo handler puro
`src/nomos/council/chat_disabled.py::handle_disabled_chat_command`, que
devolve a mensagem `[NOMOS-MC-CHAT-DISABLED]` e:

```text
MOTOR_COUNCIL_CHAT_ENABLED = False
```

O handler devolve **`None`** para qualquer mensagem que não comece com
`/conselho` (contrato do loop do chat, que só imprime quando o handler
responde). Nenhum uso atual chama o orquestrador, o harness ou o kernel real.

A CLI, em contraste, **já** tem o dry-run funcional desde MC15-UX
(`nomos conselho simular "..."` via `src/nomos/council/cli_dry_run.py`). Esta
spec traz o chat para o mesmo nível, no futuro.

## 4. Non-goals

- Não habilitar `/conselho simular` nesta fase (é MC18-UX).
- Não executar motor real, cloud, rede, subprocess, em nenhuma hipótese.
- Não chamar policy/audit/vault/approval reais.
- Não persistir histórico do Council no chat.
- Não abrir um segundo caminho de execução real: o chat dry-run deve reusar
  exatamente o `CouncilOrchestratorDryRun`, não uma cópia paralela.
- Não introduzir um modo "chat cloud" para o Council.

## 5. Future Command

```text
/conselho simular <texto>
```

Regras futuras (a valer desde a primeira implementação, MC18-UX):

- deve chamar **somente** `CouncilOrchestratorDryRun`;
- **não** deve chamar `LocalExecutionHarness.execute`;
- **não** deve chamar policy real (`nomos.kernel.policy`);
- **não** deve chamar audit real (`nomos.kernel.audit`);
- **não** deve chamar vault real (`nomos.kernel.vault`);
- **não** deve persistir (nem escrever no histórico de memória/conversa);
- **não** deve ecoar o prompt do usuário;
- deve retornar uma resposta humana **redigida**;
- pode ter um modo JSON futuro **apenas** se/quando o chat suportar saída
  estruturada (o chat amigável hoje é texto); montado manualmente, nunca via
  `result.to_dict()`;
- deve **falhar fechado** para flags proibidas e modo inválido.

Todos os **outros** subcomandos de `/conselho` (raiz, `perguntar`, `revisar`,
`status`, `modos`, `explicar`, desconhecidos) **continuam desabilitados** após
MC18-UX — só `simular` sai do esqueleto, espelhando a CLI.

## 6. Input Contract

Entrada textual do chat, já com o prefixo `/conselho simular`:

```text
/conselho simular <texto livre> [--modo <m>] [--privado] [--json] [--iniciante] [--avancado]
```

- `<texto livre>` é o prompt; é **usado** para alimentar o orquestrador, mas
  **nunca** aparece na resposta.
- O parsing futuro deve seguir o padrão do CLI MC15 (`cli_dry_run.simular`):
  separação manual de flags e prompt (sem `argparse`), reconhecendo apenas as
  flags permitidas e recusando o resto.
- `session_id` do orquestrador deve ser um identificador **fixo** do chat
  (ex.: `chat-conselho-simular`), nunca derivado do prompt, sem relógio/
  aleatoriedade.
- Modo default: `balanceado`.

## 7. Output Contract

- **Humano (permitido)**: bloco `[NOMOS-MC-CHAT-DRY-RUN]` (ver §12).
- **Humano (bloqueado pelo gate)**: bloco `[NOMOS-MC-CHAT-GATE-BLOCKED]`
  (ver §12), sem nunca exibir o conteúdo bloqueado.
- **JSON futuro (se suportado)**: payload mínimo escalar (ver §13), montado à
  mão, nunca `result.to_dict()`.
- **Erro de uso** (flag proibida / modo inválido / exceção do orquestrador):
  bloco `[NOMOS-MC-CHAT-DENIED]` (ver §10), sem ecoar o token nem o prompt.

O handler deve continuar devolvendo `None` para mensagens não relacionadas.

## 8. Privacy Rules

O futuro `/conselho simular` **não pode exibir** em nenhuma saída (humana,
JSON, erro, log, arquivo):

```text
prompt
content
final_content
candidate_content
engine_id
secret
token
api_key
authorization
bearer
```

O prompt vai **apenas** para o orquestrador (que já o mantém metadata-only) e
nunca é impresso. O chat não pode gravar o texto do Council na memória/conversa
nesta trilha dry-run.

## 9. Redaction Rules

A saída só pode conter **campos escalares seguros**:

```text
dry_run=true
allowed=true/false
blocked=true/false
would_execute=false
would_write_audit=false
private_mode=true/false
persist_allowed=true/false
failure_code=<código redigido ou null>
```

`failure_code` é um enum (`ORCH_*`), nunca conteúdo. Nenhum trace, envelope
final ou lista de candidatos pode ser serializado.

## 10. Failure Modes

Códigos de falha futuros (nomes canônicos para o chat dry-run):

| Código | Situação |
|---|---|
| `CHAT_DRY_RUN_DISABLED` | fase/flag não habilitou o dry-run no chat |
| `CHAT_FORBIDDEN_FLAG` | flag proibida presente (§11) |
| `CHAT_INVALID_MODE` | `--modo` com valor inválido |
| `CHAT_ORCHESTRATOR_FAILED` | exceção inesperada do orquestrador (fail-closed) |
| `CHAT_GATE_BLOCKED` | Policy Gate dry-run negou |
| `CHAT_PRIVATE_MODE_NO_PERSIST` | modo privado força `persist_allowed=false` |
| `CHAT_JSON_REDACTED` | saída JSON montada só com escalares seguros |
| `CHAT_UNKNOWN_SUBCOMMAND_DISABLED` | subcomando de `/conselho` não reconhecido |

Todos resolvem para uma resposta segura, sem conteúdo bruto nem prompt.

## 11. Forbidden Flags

Estas flags devem **sempre** falhar fechado (nunca habilitam nada):

```text
--real
--enable
--ativar
--force
--unsafe
--cloud
--audit-real
--policy-real
--vault-real
--engine-real
```

Saída futura esperada:

```text
[NOMOS-MC-CHAT-DENIED] Flag não permitida para Motor Council Chat.
Nada foi executado.
Nada foi persistido.
```

A flag **não** deve ser ecoada se contiver conteúdo sensível; a mensagem usa
texto fixo, sem interpolar o token do usuário.

## 12. Integration with CouncilOrchestratorDryRun

O chat dry-run futuro deve reusar o orquestrador exatamente como a CLL:

```text
CouncilOrchestrationInput(session_id="chat-conselho-simular",
                          prompt=<texto>, mode=<mapeado>, private_mode=<bool>)
  -> CouncilOrchestratorDryRun().run(entrada)
  -> ler apenas escalares: allowed, blocked, failure_code
```

Mapa de modos pt → interno (idêntico ao CLI):

```text
rapido     -> fast
balanceado -> balanced   (default)
critico    -> critical
paranoico  -> paranoid   (implica private_mode=true)
```

Regras: `--privado` força `persist_allowed=false`; `--modo paranoico` implica
privado/local-only; modo inválido falha fechado; nenhum modo usa cloud. Nunca
chamar `LocalExecutionHarness.execute`. Nunca construir `_paths()` nem
Vault/Policy/Audit reais para este comando.

## 13. Interaction with amigavel.py

A implementação futura, no loop de `amigavel.iniciar_chat`, deve **preservar**:

```text
mensagem não relacionada  => None (o chat segue o fluxo normal)
/conselho (raiz)          => fail-closed / disabled
/conselho <desconhecido>  => fail-closed / disabled
/conselho simular ...     => dry-run somente
```

E deve **garantir**:

- não capturar mensagens que não começam com `/conselho`;
- não ecoar o prompt;
- não construir contexto sensível (`_paths()`), Vault/Policy/Audit reais;
- rotear `simular` para um handler dry-run (novo módulo, ex.:
  `chat_dry_run.py`, espelhando `cli_dry_run.py`) e todo o resto para o
  `chat_disabled` atual.

O ramo atual `if linha == "/conselho" or linha.startswith("/conselho "):`
deve evoluir para distinguir `simular` dos demais, sem quebrar o contrato
`None` para mensagens não-`/conselho`.

## 14. Beginner Mode UX

`/conselho simular <texto> --iniciante` (ou o padrão, sem flag): resposta
curta e amigável, ainda redigida:

```text
[NOMOS-MC-CHAT-DRY-RUN] Simulei o conselho com segurança — nada saiu da sua
máquina, nenhum motor rodou de verdade e nada foi gravado.
(dry-run: allowed=true)
```

Sem jargão, sem trace, sem conteúdo. O modo iniciante nunca revela mais do que
o avançado — apenas apresenta os mesmos escalares de forma mais simples.

## 15. Advanced Mode UX

`/conselho simular <texto> --avancado`: mesmos escalares, formato técnico:

```text
[NOMOS-MC-CHAT-DRY-RUN] dry_run=true allowed=true blocked=false
would_execute=false would_write_audit=false private_mode=false
persist_allowed=true failure_code=null
```

Continua sem prompt/conteúdo/engine_id. O modo avançado é uma formatação
diferente dos **mesmos** campos seguros — não expõe nada a mais.

## 16. JSON Output Future Shape

Exemplo permitido (`--json`, só se o chat suportar saída estruturada):

```json
{
  "dry_run": true,
  "allowed": true,
  "blocked": false,
  "would_execute": false,
  "would_write_audit": false,
  "private_mode": false,
  "persist_allowed": true,
  "failure_code": null
}
```

Em modo privado: `"private_mode": true`, `"persist_allowed": false`.

**Proibido** usar `result.to_dict()` — ele pode carregar `trace`/
`final_envelope`/`audit_result` e, por tabela, conteúdo. O JSON futuro deve ser
montado **manualmente** com os campos escalares seguros, exatamente como o CLI
MC15 fez em `cli_dry_run._render_json`.

## 17. Security Constraints

- O módulo futuro (`chat_dry_run.py`) deve importar só stdlib + o orquestrador
  dry-run + o `chat_disabled` atual. Sem rede/subprocess/threading/asyncio/SDK
  cloud/motor; sem `local_harness`/`kernel.policy`/`kernel.vault`/
  `kernel.audit`/router/cognição.
- Sem `os.environ`/`open(`/`Path.write_*`/`time`/`datetime.now`/`random`.
- Sem `_paths()` para o comando; o roteamento acontece antes de qualquer
  contexto de kernel.
- Prompt nunca ecoado; JSON montado à mão; exceção do orquestrador vira
  bloqueio seguro.
- A constante `MOTOR_COUNCIL_CHAT_ENABLED` continuará existindo; a habilitação
  de `simular` será por **roteamento explícito** (código revisado), não por
  flip de flag — como já é na CLI.

## 18. Future Test Plan

Testes futuros obrigatórios (a implementar em MC18-UX+, não agora):

```text
test_chat_conselho_simular_dry_run_allowed
test_chat_conselho_simular_does_not_echo_prompt
test_chat_conselho_simular_json_redacted
test_chat_conselho_simular_private_no_persist
test_chat_conselho_simular_paranoico_private
test_chat_conselho_simular_forbidden_flags_denied
test_chat_conselho_simular_invalid_mode_denied
test_chat_conselho_simular_gate_blocked_hides_content
test_chat_conselho_simular_does_not_call_harness
test_chat_conselho_simular_does_not_call_policy_vault_audit
test_chat_conselho_simular_does_not_use_result_to_dict
test_chat_conselho_non_command_still_ignored
```

Mais os testes de pureza AST do novo módulo (rede/subprocess/cloud/FS-env/
tempo-random/harness-kernel), espelhando os do `cli_dry_run`.

## 19. Implementation Phases

```text
MC18-UX — Chat Dry-run Handler Implementation
          (novo chat_dry_run.py + roteamento de `simular` no amigavel;
           demais subcomandos seguem desabilitados)
MC19-UX — Chat Dry-run Integration Tests
          (bateria completa pelo loop real, se não couber toda na MC18)
MC20-UX — Chat Help/Docs Alignment
          (/ajuda e README refletindo que `simular` roda dry-run no chat)
```

Alternativa compacta: **MC18-UX — Chat Dry-run Implementation** (handler +
testes + docs num só passo), se o escopo permanecer pequeno e revisável.
Nenhuma dessas fases é executada aqui.

## 20. Acceptance Criteria

Checklist para considerar esta **spec** aceita:

- [x] `SPEC_ONLY=true`, `IMPLEMENTATION=false`, `CHAT_DRY_RUN_ENABLED=false`.
- [x] Estado atual documentado (tudo desabilitado; `None` para não-comando).
- [x] Futuro comando `/conselho simular` e suas regras definidos.
- [x] Contratos de entrada/saída, privacidade e redaction definidos.
- [x] Flags proibidas (10) e failure modes (8) listados.
- [x] Integração com `CouncilOrchestratorDryRun` e `amigavel.py` especificada,
      preservando o contrato `None` e o fail-closed dos demais subcomandos.
- [x] JSON futuro montado à mão (proibido `result.to_dict()`).
- [x] Plano de testes futuros (12 nomes) e fases de implementação (MC18+).
- [x] Nenhum código funcional, comando real ou alteração de runtime.
