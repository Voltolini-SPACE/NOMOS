# NOMOS Motor Council — Shared Output/Redaction Helper Specification v1

## 1. Status

```text
SPEC_ONLY=true               # esta é a spec; o helper foi implementado em MC21
API_SKETCH_ONLY=true         # (§16 era esboço; a API real está em safe_output.py)
HELPER_IMPLEMENTED=MC21_DONE
HELPER_ADOPTED_BY_CLI=false  # migração é MC22
HELPER_ADOPTED_BY_CHAT=false # migração é MC23
```

> **Atualizado em MC21.** O helper especificado aqui **foi implementado** em
> `src/nomos/council/safe_output.py` (fase MC21), de forma **isolada** — a CLI
> e o chat **ainda não** o adotaram (migração reservada para MC22/MC23). A API
> real (`CouncilSafeOutput` + `build_safe_output`/`render_*`) segue o esboço da
> §16 desta spec; onde a implementação precisou decidir detalhes, o contrato de
> segurança foi preservado (ver
> `docs/missions/MOTOR_COUNCIL_MC21_SHARED_REDACTION_HELPER_IMPLEMENTATION.md`).

Este documento é a **especificação canônica** da unificação segura da lógica
de **saída/redação** hoje duplicada entre a CLI (`nomos conselho simular`) e o
chat (`/conselho simular`). O helper já existe (MC21); a adoção por cada
superfície é uma fase de refactor posterior (MC22/MC23) que **não** deve tocar
em nenhuma trava de execução real.

## 2. Objective

Definir um contrato único de saída redigida para o Motor Council dry-run, de
modo que uma implementação futura possa substituir a duplicação atual por um
helper compartilhado **sem** enfraquecer nenhuma garantia de segurança e
**sem** habilitar execução real. O helper futuro deve produzir exatamente as
mesmas garantias que CLI e chat já entregam hoje, com o benefício de haver
**uma** fonte de verdade para redação e formato.

## 3. Current State

Hoje existem **duas implementações paralelas**, ambas entregues e testadas:

| Item | `src/nomos/council/cli_dry_run.py` (MC15) | `src/nomos/council/chat_dry_run.py` (MC18) |
|---|---|---|
| Entrada | tokens da CLI (após `conselho`) | string do chat (`/conselho ...`) |
| Saída | **imprime** e devolve `int` (exit code) | **devolve `str`** (o loop faz `say(...)`) |
| Chama | só `CouncilOrchestratorDryRun` | só `CouncilOrchestratorDryRun` |
| `result.to_dict()` | não usa | não usa |
| JSON | montado à mão (8 escalares) | montado à mão (8 escalares) |
| Prompt ecoado | nunca | nunca |
| Harness/policy/audit/vault reais | nunca | nunca |
| Persistência | não | não |
| Prefixo humano | `[NOMOS-MC-DRY-RUN]` "…simulado com sucesso." | `[NOMOS-MC-CHAT-DRY-RUN]` "…simulado com segurança." |
| Gate-blocked | `[NOMOS-MC-GATE-BLOCKED]` | `[NOMOS-MC-CHAT-GATE-BLOCKED]` |
| Outro bloqueio | `[NOMOS-MC-BLOCKED]` | `[NOMOS-MC-CHAT-BLOCKED]` |
| Flag negada | `[NOMOS-MC-CLI-DENIED]` | `[NOMOS-MC-CHAT-DENIED]` |
| Flags proibidas | **8** (`--real`,`--enable`,`--ativar`,`--force`,`--unsafe`,`--cloud`,`--audit-real`,`--policy-real`) | **10** (as 8 + `--vault-real`,`--engine-real`) |
| Mapa de modos | idêntico (`rapido/balanceado/critico/paranoico`) | idêntico |

A duplicação é **aceitável temporariamente** (cada superfície nasceu numa fase
separada, com testes próprios), mas deve ser reduzida numa **fase própria de
refactor**, nunca combinada com habilitação de execução real.

**Achado desta análise (divergência real):** o conjunto de flags proibidas da
CLI (8) é um **subconjunto** do conjunto do chat (10) — a CLI hoje **não**
lista `--vault-real` nem `--engine-real`. Na prática isso não abre execução
real (a CLI trata flags desconhecidas como fail-closed de qualquer forma), mas
é uma inconsistência de contrato que um helper compartilhado eliminaria. A
correção **não** é feita nesta missão (SPEC-only); fica registrada para o
refactor.

## 4. Non-goals

- Não implementar o helper (é MC21+).
- Não refatorar `cli_dry_run.py` nem `chat_dry_run.py` agora.
- Não alterar prefixos, mensagens ou exit codes existentes nesta missão.
- Não habilitar execução real, cloud, rede, subprocess, policy/audit/vault
  reais ou persistência.
- Não unificar o **parsing** de flags nesta spec (foco é saída/redação); o
  parsing pode ser tratado numa spec/fase separada se necessário.

## 5. Existing CLI Output Contract

Sucesso (permitido), impresso e exit `0`:

```text
[NOMOS-MC-DRY-RUN] Motor Council simulado com sucesso.
DRY_RUN=true
REAL_ENGINE_EXECUTION=false
REAL_POLICY=false
REAL_AUDIT=false
REAL_VAULT=false
PERSISTENCE=false
```

JSON (`--json`), 8 escalares, `sort_keys=True`:

```json
{"allowed": true, "blocked": false, "dry_run": true, "failure_code": null,
 "persist_allowed": true, "private_mode": false, "would_execute": false,
 "would_write_audit": false}
```

Negado (flag proibida/modo inválido/texto ausente/exceção), exit `3`:

```text
[NOMOS-MC-CLI-DENIED] <motivo fixo>
Nada foi executado. Nada foi persistido.
```

## 6. Existing Chat Output Contract

Sucesso (permitido), devolvido como string:

```text
[NOMOS-MC-CHAT-DRY-RUN] Conselho simulado com segurança.
DRY_RUN=true
REAL_ENGINE_EXECUTION=false
REAL_POLICY=false
REAL_AUDIT=false
REAL_VAULT=false
PERSISTENCE=false
```

JSON (`--json`), **os mesmos 8 escalares** da CLI, `sort_keys=True`. Negado:

```text
[NOMOS-MC-CHAT-DENIED] <motivo fixo>
Nada foi executado.
Nada foi persistido.
```

Diferenças de forma vs. CLI: prefixos com `CHAT`, texto humano "…com
segurança" vs. "…com sucesso", retorno `str` vs. impressão+`int`, e o conjunto
de flags proibidas maior (10 vs. 8).

## 7. Shared Security Invariants

O helper futuro deve preservar, sem exceção, para as duas superfícies:

```text
prompt nunca ecoado
content / final_content / candidate_content nunca ecoados
engine_id nunca ecoado
secret / token / api_key / authorization / bearer nunca ecoados
result.to_dict() proibido
JSON montado manualmente só com escalares seguros
saída humana redigida
falhas fail-closed (flag proibida / modo inválido / exceção)
would_execute=false e would_write_audit=false sempre
private_mode ⇒ persist_allowed=false
```

## 8. Forbidden Data

O helper futuro **nunca** pode emitir (em humano, JSON, erro, log ou arquivo):

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
trace
audit_envelope
candidate
raw_result
repr(result)
result.to_dict()
```

## 9. Allowed Scalar Fields

Somente estes campos escalares seguros podem sair:

```text
dry_run           (bool, sempre true nesta fase)
allowed           (bool)
blocked           (bool)
would_execute     (bool, sempre false)
would_write_audit (bool, sempre false)
private_mode      (bool)
persist_allowed   (bool)
failure_code      (str | null; um código ORCH_*/enum, nunca conteúdo)
mode              (str NORMALIZADO: fast|balanced|critical|paranoid — nunca o texto do usuário)
interface         (str: "cli" | "chat")
```

`mode` só pode ser o modo **normalizado** (valor interno do `CouncilMode`),
jamais o token digitado. `interface` só pode ser `"cli"` ou `"chat"`.

> Nota: `mode` e `interface` **ainda não** aparecem no JSON atual (CLI/chat
> emitem os 8 escalares sem eles). São **acréscimos propostos** para o helper
> unificado; incluí-los é opcional e, se incluídos, seguem as restrições
> acima. A migração deve decidir explicitamente se os adiciona (mudança de
> contrato pública) ou mantém os 8 atuais.

## 10. Human Output Contract

O helper deve produzir o mesmo bloco humano de hoje, escolhendo o prefixo por
`interface`:

```text
interface=cli  -> [NOMOS-MC-DRY-RUN] Motor Council simulado com sucesso.
interface=chat -> [NOMOS-MC-CHAT-DRY-RUN] Conselho simulado com segurança.
```

seguido, em ambos, do bloco fixo:

```text
DRY_RUN=true
REAL_ENGINE_EXECUTION=false
REAL_POLICY=false
REAL_AUDIT=false
REAL_VAULT=false
PERSISTENCE=false
```

**Decisão de desenho (registrada):** o helper recebe `interface="cli|chat"` e
**formata o prefixo de acordo**, mantendo os prefixos distintos que já
existem (compatibilidade retroativa). Unificar para um prefixo único seria uma
mudança pública de contrato e **não** é recomendada sem aprovação explícita.

## 11. JSON Output Contract

Exemplo permitido (proposto, com `interface`/`mode`):

```json
{
  "interface": "cli",
  "dry_run": true,
  "allowed": true,
  "blocked": false,
  "would_execute": false,
  "would_write_audit": false,
  "private_mode": false,
  "persist_allowed": true,
  "failure_code": null,
  "mode": "balanced"
}
```

Exemplo privado:

```json
{
  "interface": "chat",
  "dry_run": true,
  "allowed": true,
  "blocked": false,
  "would_execute": false,
  "would_write_audit": false,
  "private_mode": true,
  "persist_allowed": false,
  "failure_code": null,
  "mode": "paranoid"
}
```

O JSON deve ser montado a partir de um objeto de campos escalares (ver §16),
**nunca** por serialização do resultado do orquestrador. Se a migração optar
por **não** mudar o contrato público, os 8 escalares atuais são mantidos e
`interface`/`mode` ficam de fora — a spec permite ambas as opções, desde que a
escolha seja explícita e testada.

## 12. Gate-blocked Output Contract

```text
interface=cli  -> [NOMOS-MC-GATE-BLOCKED] Resposta bloqueada pelo Policy Gate dry-run.
interface=chat -> [NOMOS-MC-CHAT-GATE-BLOCKED] Resposta bloqueada pelo Policy Gate dry-run.
```

seguido, obrigatoriamente, de:

```text
Nada foi executado.
Nada foi persistido.
Conteúdo bloqueado não será exibido.
```

O conteúdo final bloqueado **nunca** é exibido.

## 13. Exception Output Contract

Qualquer exceção do orquestrador vira bloqueio seguro, sem traceback nem
prompt:

```text
interface=cli  -> [NOMOS-MC-BLOCKED] ... (fail-closed)
interface=chat -> [NOMOS-MC-CHAT-BLOCKED] ... (fail-closed)
```

com "Nada foi executado. Nada foi persistido." Flag proibida/desconhecida:

```text
interface=cli  -> [NOMOS-MC-CLI-DENIED] <motivo fixo>
interface=chat -> [NOMOS-MC-CHAT-DENIED] <motivo fixo>
```

A flag ou token do usuário **nunca** é ecoada — o motivo é texto fixo.

## 14. Private Mode Output Contract

- `--privado` ⇒ `private_mode=true`, `persist_allowed=false`.
- `--modo paranoico` ⇒ implica `--privado` (mesmo efeito).
- No JSON: `"private_mode": true, "persist_allowed": false`.
- No humano: o bloco padrão (nenhum campo extra revela conteúdo).

## 15. Forbidden APIs

O helper futuro **não pode** usar, para produzir saída:

```text
result.to_dict()
repr(result)
vars(result)
dataclasses.asdict(result)
json.dumps(result)          # dump do resultado inteiro
```

E, como todos os módulos do Council, **não pode**:

```text
open() / Path.write_text / Path.write_bytes
os.environ / os.getenv
time / datetime.now / random / secrets
imports de rede (socket/http/urllib/requests/httpx/…)
subprocess / threading / multiprocessing / asyncio
SDKs de nuvem (openai/anthropic/google/…) e motores (ollama/llama_cpp/…)
nomos.council.local_harness / nomos.kernel.policy|vault|audit reais
```

## 16. Future Helper API Sketch

```python
# API_SKETCH_ONLY=true — NÃO implementar nesta missão.
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class CouncilSafeOutput:
    interface: Literal["cli", "chat"]
    dry_run: bool
    allowed: bool
    blocked: bool
    would_execute: bool
    would_write_audit: bool
    private_mode: bool
    persist_allowed: bool
    failure_code: str | None
    mode: str


def build_safe_output(result, *, interface, mode, private_mode) -> CouncilSafeOutput:
    """Lê SÓ escalares do resultado do orquestrador (allowed/blocked/
    failure_code) — nunca trace/envelope/to_dict — e devolve um objeto seguro."""


def render_human_output(output: CouncilSafeOutput) -> str: ...
def render_json_output(output: CouncilSafeOutput) -> str: ...
def render_denied_output(interface, reason: str) -> str: ...
def render_gate_blocked_output(interface) -> str: ...
```

CLI e chat futuros chamariam `build_safe_output(...)` + o `render_*`
apropriado, cada um adaptando só o "efeito de borda" (a CLI imprime e devolve
exit code; o chat devolve string).

## 17. Migration Plan

```text
MC21 — Shared Redaction Helper Implementation
       (cria o módulo helper + testes de segurança próprios; NÃO migra
        CLI/Chat ainda — os dois seguem com seu código atual)
MC22 — CLI migration to shared helper
       (cli_dry_run passa a usar o helper; testes da CLI inalterados em
        comportamento, só a fonte muda)
MC23 — Chat migration to shared helper
       (chat_dry_run passa a usar o helper; idem)
MC24 — Regression/security hardening
       (remove duplicação residual, reconcilia o conjunto de flags proibidas
        8↔10, e prova por teste que CLI e chat compartilham o mesmo contrato
        escalar)
```

Cada fase com CI verde e testes próprios; nenhuma delas habilita execução
real. Uma variante compacta (helper + migração das duas superfícies numa fase)
só é aceitável se o diff permanecer pequeno e revisável, mas a preferência é
migrar uma superfície por vez.

## 18. Future Test Plan

```text
test_shared_output_never_uses_to_dict
test_shared_output_json_contains_only_safe_scalars
test_shared_output_human_does_not_echo_prompt
test_shared_output_private_persist_false
test_shared_output_gate_blocked_hides_content
test_shared_output_forbidden_flag_hides_flag
test_cli_and_chat_outputs_share_same_scalar_contract
test_shared_output_module_no_network_imports
test_shared_output_module_no_filesystem_env_time_random
```

Mais os testes AST de pureza do módulo novo, espelhando os de `cli_dry_run`/
`chat_dry_run`.

## 19. Failure Modes

| Código | Situação |
|---|---|
| `SHARED_OUTPUT_DISABLED` | helper ainda não implementado (estado atual) |
| `SHARED_FORBIDDEN_DATA` | tentativa de emitir um campo proibido (§8) — deve ser impossível por construção |
| `SHARED_TO_DICT_FORBIDDEN` | qualquer uso de `result.to_dict()`/serialização do resultado inteiro |
| `SHARED_INTERFACE_INVALID` | `interface` fora de `{cli, chat}` |
| `SHARED_MODE_NOT_NORMALIZED` | `mode` contendo texto do usuário em vez do valor normalizado |
| `SHARED_GATE_BLOCKED_LEAK` | tentativa de exibir conteúdo bloqueado pelo gate |

Todos devem ser **impossíveis por construção** no helper (o objeto
`CouncilSafeOutput` só carrega escalares seguros), não apenas evitados por
convenção.

## 20. Acceptance Criteria

Checklist para considerar esta **spec** aceita:

- [x] `SPEC_ONLY=true`, `IMPLEMENTATION=false`, `REFACTOR=false`.
- [x] Estado atual documentado (duas implementações paralelas) com a tabela de
      divergências, incluindo o achado das flags proibidas 8↔10.
- [x] Invariantes de segurança compartilhadas listadas.
- [x] Dados proibidos e campos escalares permitidos definidos.
- [x] Contratos humano/JSON/gate-blocked/exceção/modo privado definidos por
      `interface`.
- [x] APIs proibidas listadas (incl. `to_dict`/`repr`/`asdict`/`vars`).
- [x] Esboço de API futura (`CouncilSafeOutput` + `build_/render_*`) marcado
      `API_SKETCH_ONLY=true`.
- [x] Plano de migração (MC21–MC24) e plano de testes futuros (9 nomes).
- [x] Nenhum código funcional, refactor ou alteração de runtime/testes.
