# NOMOS Motor Council — Technical Specification v1

## 1. Status

```text
SPEC_ONLY=true
IMPLEMENTATION=false
```

Este documento é **apenas especificação**. Nenhum código funcional, comando de
CLI/chat, motor, agente, skill ou rotina é criado ou alterado por ele. Ele
descreve o desenho técnico do **NOMOS Motor Council** para orientar uma
implementação incremental futura, e é escrito para respeitar, sem exceção, as
garantias já existentes do NOMOS: local-first, fail-closed, zero telemetria,
cloud opt-in por uso, Policy Gate A0–A6, modo privado, redaction, audit log com
âncora HMAC no cofre, agent boundary e skill boundary.

Base do desenho: kernel na tag `v1.2.0rc3-audit-anchored` (commit 657ca21), com
`kernel/policy.py` (gate A0–A6), `kernel/localidade.py` (cadeado só-local),
`kernel/vault.py` (Argon2id), `kernel/audit.py` + `kernel/audit_anchor.py`
(cadeia + HMAC ancorado), `agents/boundary.py` e `ext/skills.py`.

## 2. Objective

O Motor Council permite que **múltiplos motores** (modelos) gerem, revisem,
julguem e arbitrem respostas **antes do envio ao usuário**, aumentando correção,
segurança e detecção de alucinação em tarefas de maior risco — **sem** abrir mão
de nenhuma garantia local-first.

O Council **não** é "um motor principal com palpite dos outros". É um pipeline
com papéis separados e contratos explícitos, onde:

- respostas candidatas são **anonimizadas** antes do julgamento;
- juízes avaliam por **rubrica estruturada**, não texto livre;
- um árbitro compõe a resposta final **sem fingir certeza**;
- a resposta final **sempre** passa pelo Policy Gate antes de ir ao usuário;
- tudo é auditado com conteúdo sensível **redigido**, e em modo privado **nada
  detalhado é persistido**.

## 3. Non-goals

- Não substitui o roteador atual (`cognition/router.py`); o Council é uma camada
  **opcional e desligada por padrão** acima da geração.
- Não adiciona telemetria, "voto na nuvem" nem envio silencioso de dados.
- Não cria um novo caminho de autorização: **todo** efeito colateral continua
  passando pelo mesmo `policy.gate`.
- Não permite que o árbitro **execute** ações — ele só compõe texto.
- Não torna a nuvem obrigatória; motores de nuvem seguem opt-in, com cadeado
  aberto + chave no cofre + aprovação por uso.
- Não implementa nada nesta fase (MC0 = SPEC only).

## 4. Architecture Overview

```text
                 (texto DIGITADO pelo usuário — única fonte de intenção)
                                     │
                          ┌──────────▼───────────┐
                          │   Risk Classifier     │  A0..A6 + flags de sensibilidade
                          └──────────┬───────────┘
                                     │ RiskAssessment
                          ┌──────────▼───────────┐
                          │    Council Policy     │  decide modo e se o Council roda
                          └──────────┬───────────┘
                                     │ CouncilPolicy (mode, counts, cloud_allowed)
                          ┌──────────▼───────────┐
                          │  Candidate Generators │  N motores isolados; sem ver-se
                          └──────────┬───────────┘
                                     │ AnswerCandidate[]  (anonimizados)
                          ┌──────────▼───────────┐
                          │    Blind Judge Pool   │  M juízes; rubrica estruturada
                          └──────────┬───────────┘
                                     │ JudgeScore[] + DisagreementReport
                          ┌──────────▼───────────┐
                          │        Arbiter        │  compõe final; marca incerteza
                          └──────────┬───────────┘
                                     │ ArbiterDecision (texto, sem executar)
                          ┌──────────▼───────────┐
                          │      Policy Gate      │  A0..A6 (fail-closed)
                          └──────────┬───────────┘
                                     │ (ALLOW/REQUIRE_APPROVAL/DENY)
                          ┌──────────▼───────────┐
                          │    Final Response     │  ao usuário
                          └──────────┬───────────┘
                                     │
                          ┌──────────▼───────────┐
                          │       Audit Log       │  redigido + (opcional) âncora HMAC
                          └──────────────────────┘
```

Cada etapa tem contrato (entrada/saída), riscos e testes previstos (seções 6–13,
16, 17).

## 5. Council Modes

Quatro modos; a escolha é do Council Policy a partir do risco e da preferência
declarada. Todos os modos honram local-first e fail-closed.

### 5.1 Rápido (fast)
- **Uso**: perguntas simples/baixo risco.
- **Pipeline**: 1 gerador; 1 revisor leve opcional; **sem conselho completo**.
- **Objetivo**: latência mínima; não chamar o Council quando não agrega.

### 5.2 Balanceado (balanced)
- **Uso**: comunicação, escrita, planejamento, resposta a cliente, resumo
  importante.
- **Pipeline**: 2–3 candidatos; 2 juízes; 1 árbitro; **gate final**.

### 5.3 Crítico (critical)
- **Uso**: código, segurança, jurídico, financeiro, decisões operacionais.
- **Pipeline**: 3–5 candidatos; 3 juízes; árbitro; **Policy Gate obrigatório**;
  **audit detalhado redigido**.

### 5.4 Paranoico (paranoid)
- **Uso**: dados sensíveis, cloud proibida, ações de risco.
- **Pipeline**: **somente motores locais**; **sem persistência** se modo privado;
  **sem cloud**; **sem execução automática**; aprovação humana quando necessário.

| Modo | candidatos | juízes | árbitro | gate final | cloud | persistência |
|---|---|---|---|---|---|---|
| rápido | 1 | 0–1 | — | herda do fluxo | opt-in | normal |
| balanceado | 2–3 | 2 | 1 | sim | opt-in | normal |
| crítico | 3–5 | 3 | 1 | obrigatório | opt-in | audit detalhado redigido |
| paranoico | ≥2 locais | ≥2 | 1 | obrigatório | **proibido** | nada se privado |

## 6. Risk Classifier

- **Objetivo**: mapear a solicitação (texto digitado) para um nível A0–A6 e
  flags de sensibilidade, para decidir modo e se o Council roda.
- **Entrada**: `texto_confiavel` (apenas o que o usuário digitou — nunca
  conteúdo recuperado, conforme `cognition/prompt_guard.py`), contexto de
  política e localidade.
- **Saída**: `RiskAssessment` (nível A0–A6, `sensitive_data: bool`,
  `needs_cloud_denied: bool`, `recommended_mode`).
- **Riscos**: classificar para baixo (subestimar risco). Mitigação:
  fail-closed — em dúvida, escalar o modo (nunca rebaixar) e nunca marcar
  `sensitive_data=false` por omissão.
- **Regra**: o classificador **não** executa nada e **não** chama cloud.

## 7. Candidate Generators

- **Objetivo**: gerar respostas independentes por N motores.
- **Isolamento**: cada gerador recebe o mesmo prompt do usuário e **não vê** as
  respostas dos outros; conteúdo recuperado entra **envelopado como DADO**
  (`prompt_guard.envelopar`), nunca como instrução.
- **Anonimização**: cada `AnswerCandidate` recebe um id opaco (ex.: `cand-«hex»`)
  e **não carrega** a identidade do motor autor até depois do julgamento.
- **Cloud**: um gerador de nuvem só é elegível se `cloud_allowed=true`
  (cadeado aberto + chave no cofre + aprovação A2+A3 por uso). Caso contrário,
  apenas geradores locais participam.
- **Riscos**: vazamento de autoria para os juízes; mitigação: mapa autor↔id fica
  fora do que o juiz recebe.

## 8. Blind Judge Pool

- **Objetivo**: avaliar candidatos **anonimizados** por rubrica estruturada.
- **Anonimização**: o juiz recebe apenas `{id, texto}` — nunca o nome do motor.
- **Impedimento de autojulgamento**: quando há motores suficientes, um motor
  **não** julga a própria resposta (o Council marca o par autor↔candidato e
  exclui esse juiz para aquele candidato). Se não houver juízes suficientes sem
  conflito, o estado é `INSUFFICIENT_JUDGES` (fail-closed; ver seção 10).
- **Saída**: `JudgeScore` estruturado (rubrica da seção 8/9), **não** texto livre.
- **Riscos**: juiz contaminado pela autoria (mitigado por anonimização); colusão
  (mitigada por diversidade de motores e pelo árbitro + gate final).

## 9. Arbiter

- **Objetivo**: compor a resposta final a partir dos scores, **sem fingir
  certeza**.
- **Regras**:
  - Se a **divergência** entre juízes/candidatos for alta, o árbitro **não**
    inventa consenso: devolve resposta com ressalva explícita ou solicita
    esclarecimento ao usuário (estado `JUDGE_DISAGREEMENT_HIGH`).
  - Se **qualquer** juiz sinaliza risco crítico (segurança/privacidade), o
    árbitro **escala ou bloqueia** (não deixa "resposta perigosa vencer por
    maioria").
  - O árbitro **não executa** nenhuma ação — só produz texto.
- **Saída**: `ArbiterDecision` (texto final + `uncertainty: low|medium|high` +
  `requires_human_approval: bool`).

## 10. Policy Gate

- A resposta final e **qualquer** efeito colateral sugerido passam pelo
  **mesmo** `policy.gate` A0–A6 do kernel (`kernel/policy.py`).
- O Council **não** cria gate próprio nem flag de bypass. Sem aprovador
  (contexto não interativo) ⇒ `REQUIRE_APPROVAL` vira negação (fail-closed).
- `A6_DESTRUCTIVE` permanece `DENY`. Uso de credencial/egress (A2/A3) continua
  exigindo aprovação por uso.
- Agente/skill que aciona o Council **não** herda permissões novas: o boundary
  do chamador (`agents/boundary.py`, `ext/skills.py`) continua valendo.

## 11. Privacy Model

- **Modo privado** (herdado de `conversations/store.py` com `:memory:`): em modo
  privado, candidatos, reviews e a decisão detalhada **não são persistidos** —
  vivem só em memória e somem ao fim da sessão.
- **Histórico/memória**: um julgamento **nunca** vira memória durável
  automaticamente; promoção a memória exige **aprovação** (fluxo de candidatas de
  `cognition/memory.py`).
- **Redaction**: todo conteúdo sensível é redigido antes de qualquer log
  (`kernel/audit.py: redact/redact_text`).
- **`/contexto`**: o Council deve ser transparente sobre o que foi enviado a
  cada motor, sem revelar segredos do cofre (segredos nunca entram no prompt).

## 12. Locality / Cloud Rules

- **Padrão**: cadeado só-local **ligado** ⇒ egress externo é `DENY` antes do gate
  (`kernel/localidade.py: bloqueia_egress`). Logo, por padrão, **só motores
  locais** participam.
- **Cloud opt-in por uso**: um motor de nuvem só participa se, para **aquela
  chamada**, houver (1) cadeado aberto, (2) chave no cofre e (3) aprovação
  aprovada no gate A2 (egress) **e** A3 (credencial) — o padrão de
  `cognition/router.py`.
- **Dados sensíveis vetam cloud**: se `RiskAssessment.sensitive_data=true`, a
  cloud é negada mesmo com cadeado aberto (`SENSITIVE_DATA_CLOUD_DENIED`).
- **Fallback nunca aciona cloud**: falta de motor local **não** "cai para a
  nuvem"; devolve `NO_ELIGIBLE_LOCAL_ENGINE` (fail-closed).

## 13. Audit Model

- **O que logar** (metadados): `session_id`, `mode`, `risk_level`,
  `candidate_count`, `judge_count`, `cloud_allowed`, estados de falha, decisão do
  gate. **Nunca** o conteúdo bruto sensível.
- **Redaction**: todo campo passa por `redact` (nome de campo sensível + padrões
  de segredo).
- **Âncora**: registros do Council entram no mesmo audit log com cadeia de hash;
  a integridade de cauda é coberta pela âncora HMAC do cofre
  (`kernel/audit_anchor.py`) quando o usuário roda `nomos logs anchor`.
- **Modo privado**: grava, no máximo, um marcador mínimo de que uma sessão
  privada ocorreu (sem candidatos/reviews/decisão detalhada).

## 14. Data Contracts

Schemas **conceituais** (não implementados). Versão `.v1` em cada `schema`.

```json
{ "schema": "nomos.council.session.v1", "session_id": "…", "mode": "critical",
  "risk_level": "A2", "local_only": true, "private_mode": false,
  "candidate_count": 3, "judge_count": 3, "cloud_allowed": false }
```

```json
{ "schema": "nomos.council.policy.v1", "mode": "critical",
  "min_candidates": 3, "max_candidates": 5, "min_judges": 3,
  "gate_final_required": true, "cloud_allowed": false,
  "persist": "redacted_metadata_only" }
```

```json
{ "schema": "nomos.council.risk.v1", "risk_level": "A2",
  "sensitive_data": true, "needs_cloud_denied": true,
  "recommended_mode": "paranoid", "reasons": ["credencial", "PII"] }
```

```json
{ "schema": "nomos.council.candidate.v1", "candidate_id": "cand-9f2a",
  "text": "…", "engine_ref": "OPAQUE_UNTIL_AFTER_JUDGING",
  "local": true, "contains_sensitive": false }
```

```json
{ "schema": "nomos.council.blind_review.v1", "candidate_id": "cand-9f2a",
  "judge_id": "judge-1", "author_conflict": false }
```

```json
{ "schema": "nomos.council.judge_score.v1", "candidate_id": "cand-9f2a",
  "judge_id": "judge-1",
  "scores": { "correctness": 4, "clarity": 5, "safety": 5, "privacy": 5,
              "usefulness": 4, "evidence": 3, "hallucination_risk": 1 },
  "followed_local_first": true, "requires_human_approval": false,
  "contains_sensitive_data": false }
```

```json
{ "schema": "nomos.council.arbiter_decision.v1", "session_id": "…",
  "final_text": "…", "uncertainty": "medium",
  "requires_human_approval": true, "executed_action": false }
```

```json
{ "schema": "nomos.council.disagreement.v1", "session_id": "…",
  "level": "high", "dimensions": ["correctness", "safety"],
  "action": "ask_clarification" }
```

```json
{ "schema": "nomos.council.audit_record.v1", "session_id": "…",
  "mode": "critical", "risk_level": "A2", "candidate_count": 3,
  "judge_count": 3, "cloud_allowed": false, "gate_effect": "REQUIRE_APPROVAL",
  "failure_state": null, "content": "[REDIGIDO]" }
```

## 15. Failure Modes

Todos **fail-closed**: em dúvida, não responde/não executa.

| Estado | Causa | Comportamento | Mensagem ao usuário | Loga? | Exige aprovação? |
|---|---|---|---|---|---|
| COUNCIL_DISABLED | Council desligado (padrão) | usa fluxo normal | — (transparente) | não | não |
| NO_ELIGIBLE_LOCAL_ENGINE | sem motor local elegível | aborta; **não** cai p/ cloud | "sem motor local disponível" | sim (metadado) | não |
| CLOUD_BLOCKED_BY_LOCAL_LOCK | cadeado só-local ligado | nega cloud, segue local | "nuvem bloqueada pelo cadeado local" | sim | não |
| SENSITIVE_DATA_CLOUD_DENIED | dado sensível + tentativa de cloud | nega cloud | "dado sensível: nuvem negada" | sim | não |
| JUDGE_DISAGREEMENT_HIGH | divergência alta | ressalva ou pede esclarecimento | "não há consenso; confirme…" | sim | pode |
| ARBITER_UNSAFE_OUTPUT | árbitro detecta saída perigosa | bloqueia/escala | "resposta bloqueada por segurança" | sim | sim |
| POLICY_GATE_DENIED | gate nega | não responde/age | mensagem honesta do gate (E002) | sim | — |
| PRIVATE_MODE_NO_PERSIST | modo privado | não persiste detalhes | "modo privado: nada foi salvo" | marcador mínimo | não |
| INSUFFICIENT_JUDGES | juízes sem conflito insuficientes | aborta o julgamento cego | "juízes insuficientes sem conflito" | sim | não |
| ENGINE_TIMEOUT | motor estourou tempo | descarta candidato; fail-closed | "um motor demorou; segui com os demais" | sim | não |
| ENGINE_FAILED | motor falhou | descarta candidato; fail-closed | "um motor falhou; segui com os demais" | sim | não |

## 16. Threat Model

| Ameaça | Mitigação esperada |
|---|---|
| Juiz contaminado pela autoria | anonimização dos candidatos antes do julgamento |
| Motor julga a si mesmo | impedimento quando há juízes suficientes; senão INSUFFICIENT_JUDGES |
| Cloud silenciosa | cadeado local + gate A2/A3 por uso; fallback nunca aciona cloud |
| Dado sensível em candidato | redaction + `SENSITIVE_DATA_CLOUD_DENIED` |
| Árbitro executa ação | proibido: árbitro só produz texto; efeitos vão ao gate |
| Agente usa o Council como bypass | mesmo `policy.gate`; boundary do agente continua |
| Skill usa o Council como bypass | permission boundary da skill continua; sem gate novo |
| Resposta perigosa vence votação | gate final + veto do árbitro por alerta crítico |
| Maioria errada | árbitro pondera incerteza; não finge consenso |
| Divergência alta | pedir esclarecimento / ressalva explícita |
| Logs vazam conteúdo sensível | redaction obrigatória antes de logar |
| Modo privado persiste reviews | proibido: `:memory:`, nada detalhado no disco |
| Prompt injection vira instrução | conteúdo recuperado envelopado como DADO (prompt_guard) |
| Julgamento vira memória durável | proibido automático; só via candidatas aprovadas |

## 17. Test Plan

Testes **futuros obrigatórios** (não implementados nesta missão):

```text
test_council_anonymizes_candidates
test_council_prevents_self_judging_when_possible
test_council_blocks_cloud_when_local_lock_enabled
test_council_blocks_cloud_for_sensitive_data
test_council_private_mode_does_not_persist_candidates
test_council_private_mode_does_not_persist_reviews
test_council_final_answer_goes_through_policy_gate
test_council_high_disagreement_does_not_fake_certainty
test_council_critical_judge_alert_blocks_or_escalates
test_council_audit_redacts_sensitive_content
test_council_agent_cannot_bypass_policy
test_council_skill_cannot_bypass_permissions
test_council_fallback_single_engine
test_council_timeout_fail_closed
test_council_no_memory_auto_write
```

## 18. Implementation Phases

| Fase | Escopo | Restrição |
|---|---|---|
| **MC0** | SPEC only | esta missão; nenhum código |
| **MC1** | Data models only | modelos puros; sem execução de motores; sem persistência |
| **MC2** | Offline simulator | fixtures fixas; **sem LLM real**; valida pipeline/estados |
| **MC3** | Local engine integration | integra **somente** motores locais |
| **MC4** | Policy gate integration | gate obrigatório antes da resposta final |
| **MC5** | Private mode + audit integration | privacidade + logs redigidos + âncora |
| **MC6** | UX/CLI/chat commands | comandos **só depois** da governança pronta |
| **MC7** | Optional cloud path | só com cadeado aberto + aprovação por uso |

Cada fase entra sob `implementation-loop-100` (SPEC → implementar → testar →
validar → evidência → entregar), com suíte verde e CI nos três SOs.

## 19. GitHub Issues Draft

> Backlog futuro. Caminhos de arquivo são **prováveis**, não criados agora.

### MC-001 — Define Council data models
**Phase:** MC1 · **Risk:** Low · **Scope:** models only
**Files likely:** `src/nomos/council/models.py`, `tests/council/test_models.py`
**Acceptance:** no engine execution; schemas validate; no persistence; tests pass.

### MC-002 — Risk Classifier (pure)
**Phase:** MC1 · **Risk:** Low · **Scope:** classification only
**Files likely:** `src/nomos/council/risk.py`, `tests/council/test_risk.py`
**Acceptance:** fail-closed (dúvida ⇒ escala); nunca marca sensitive=false por omissão; sem rede.

### MC-003 — Candidate anonymization
**Phase:** MC1 · **Risk:** Medium · **Scope:** id opaco + mapa autor fora do juiz
**Files likely:** `src/nomos/council/candidates.py`, `tests/council/test_anonymization.py`
**Acceptance:** juiz não recebe autoria; teste prova ausência do engine_ref no payload do juiz.

### MC-004 — Blind Judge (rubric)
**Phase:** MC2 · **Risk:** Medium · **Scope:** rubrica estruturada, sem texto livre
**Files likely:** `src/nomos/council/judge.py`, `tests/council/test_judge.py`
**Acceptance:** saída estruturada; autojulgamento impedido quando possível.

### MC-005 — Arbiter (no false certainty)
**Phase:** MC2 · **Risk:** Medium · **Scope:** compõe final + incerteza
**Files likely:** `src/nomos/council/arbiter.py`, `tests/council/test_arbiter.py`
**Acceptance:** divergência alta ⇒ ressalva/pergunta; nunca executa ação.

### MC-006 — Disagreement report
**Phase:** MC2 · **Risk:** Low · **Scope:** relatório de divergência
**Files likely:** `src/nomos/council/disagreement.py`, `tests/council/test_disagreement.py`
**Acceptance:** classifica nível; sugere ação (ask_clarification).

### MC-007 — Policy Gate integration
**Phase:** MC4 · **Risk:** High · **Scope:** resposta final pelo gate
**Files likely:** `src/nomos/council/gate_bridge.py`, `tests/council/test_gate.py`
**Acceptance:** sem gate novo; A6 DENY; sem aprovador ⇒ nega.

### MC-008 — Private mode integration
**Phase:** MC5 · **Risk:** High · **Scope:** `:memory:`; nada detalhado no disco
**Files likely:** `src/nomos/council/session.py`, `tests/council/test_private.py`
**Acceptance:** FS inspecionado; candidatos/reviews não persistidos.

### MC-009 — Audit redaction
**Phase:** MC5 · **Risk:** High · **Scope:** metadados redigidos + âncora
**Files likely:** `src/nomos/council/audit_bridge.py`, `tests/council/test_audit.py`
**Acceptance:** conteúdo sensível nunca logado; usa redact + audit_anchor.

### MC-010 — Local-only enforcement
**Phase:** MC3 · **Risk:** High · **Scope:** só motores locais por padrão
**Files likely:** `src/nomos/council/engines.py`, `tests/council/test_local_only.py`
**Acceptance:** cadeado ligado ⇒ nenhum motor de nuvem elegível.

### MC-011 — Cloud denial for sensitive data
**Phase:** MC7 · **Risk:** High · **Scope:** veto de cloud por sensibilidade
**Files likely:** `src/nomos/council/cloud_policy.py`, `tests/council/test_cloud_denied.py`
**Acceptance:** sensitive_data ⇒ cloud negada mesmo com cadeado aberto.

### MC-012 — Fallback single engine
**Phase:** MC3 · **Risk:** Medium · **Scope:** 1 motor local
**Files likely:** `src/nomos/council/fallback.py`, `tests/council/test_fallback.py`
**Acceptance:** com 1 motor, funciona sem fingir conselho; nunca chama cloud.

### MC-013 — Timeout / engine failure fail-closed
**Phase:** MC3 · **Risk:** Medium · **Scope:** timeout/erro por candidato
**Files likely:** `src/nomos/council/runner.py`, `tests/council/test_timeout.py`
**Acceptance:** timeout ⇒ descarta candidato, fail-closed; nunca trava.

### MC-014 — CLI (later)
**Phase:** MC6 · **Risk:** Medium · **Scope:** `nomos conselho status/on/off/testar/modo`
**Files likely:** `src/nomos/cli.py` (novo subcomando), `tests/council/test_cli.py`
**Acceptance:** só após governança; desligado por padrão; sem bypass.

### MC-015 — Chat commands (later)
**Phase:** MC6 · **Risk:** Medium · **Scope:** `/conselho` no chat
**Files likely:** `src/nomos/simple/amigavel.py`, `tests/council/test_chat.py`
**Acceptance:** transparente (`/contexto`); respeita modo privado.

### MC-016 — Docs
**Phase:** todas · **Risk:** Low · **Scope:** documentação incremental
**Files likely:** `docs/architecture/`, `docs/COUNCIL.md`
**Acceptance:** cada fase documenta contrato, riscos e testes.

## 20. Acceptance Criteria

Checklist para considerar a **spec** aceita (esta missão):

- [x] `SPEC_ONLY=true`, `IMPLEMENTATION=false`.
- [x] Pipeline (Risk → Policy → Generators → Judges → Arbiter → Gate → Response
      → Audit) descrito com contrato por etapa.
- [x] Quatro modos (rápido/balanceado/crítico/paranoico) especificados.
- [x] Contratos de dados (9 schemas conceituais) incluídos.
- [x] Rubrica de julgamento estruturada (0–5 + flags).
- [x] Regras de segurança (anonimização, sem autojulgamento, cloud opt-in,
      sem bypass por agente/skill, árbitro não executa, gate final) declaradas.
- [x] Failure modes (11 estados) com causa/comportamento/mensagem/log/aprovação.
- [x] Threat model (≥12 ameaças) com mitigação.
- [x] Test plan (15 testes futuros) listado.
- [x] Fases MC0–MC7 e ≥15 issues (MC-001…MC-016) no backlog.
- [x] Nenhuma garantia existente é violada (local-first, fail-closed, zero
      telemetria, cloud opt-in, gate A0–A6, modo privado, redaction, audit,
      vault, agent/skill boundary).
- [x] Nenhum código funcional, comando real ou alteração de runtime.
