# RELATÓRIO FINAL — MOTOR COUNCIL SPEC ONLY

## 1. Status final

STATUS_FINAL=PASS_MOTOR_COUNCIL_SPEC_ONLY

Especificação técnica canônica criada, sem qualquer implementação. Baseline
verde antes e depois; suíte intacta em 520 testes.

## 2. Baseline

| Item | Resultado |
|---|---|
| BASELINE_HEAD | 657ca21 |
| BASELINE_TAG | v1.2.0rc3-audit-anchored |
| GIT_STATUS | CLEAN (antes dos commits de docs) |
| GIT_FSCK | PASS |
| RUFF | PASS |
| PYTEST | PASS_520 |
| DOUTOR | PASS |
| PYTHON_M_NOMOS_DOUTOR | PASS |
| LOGS_VERIFY | PASS (LEGACY_UNANCHORED, rc 0 esperado) |

## 3. Documentos criados

| Arquivo | Status |
|---|---|
| docs/architecture/MOTOR_COUNCIL_SPEC_v1.md | CRIADO (20 seções) |
| docs/missions/MOTOR_COUNCIL_SPEC_ONLY_v1.md | CRIADO (este relatório) |

## 4. Escopo confirmado

```text
SPEC_ONLY=true
IMPLEMENTATION=false
```

## 5. O que foi especificado

- Pipeline com contrato por etapa: Risk Classifier → Council Policy →
  Candidate Generators → Blind Judge Pool → Arbiter → Policy Gate →
  Final Response → Audit Log.
- Quatro modos: rápido, balanceado, crítico, paranoico (com contagens de
  candidatos/juízes, gate e regras de persistência/cloud).
- Nove contratos de dados conceituais (session, policy, risk, candidate,
  blind_review, judge_score, arbiter_decision, disagreement, audit_record).
- Rubrica de julgamento estruturada (correção/clareza/segurança/privacidade/
  utilidade/evidência/risco-de-alucinação 0–5 + flags), saída estruturada.
- Regras de segurança: anonimização, impedimento de autojulgamento, cloud
  opt-in por uso, veto de cloud para dado sensível, sem bypass por agente/skill,
  árbitro não executa, gate final obrigatório, sem certeza falsa em divergência.
- 11 failure modes fail-closed com causa/comportamento/mensagem/log/aprovação.
- Threat model com 14 ameaças e mitigação (ancorado nas primitivas reais:
  policy gate, localidade, vault, audit_anchor, prompt_guard, boundaries).
- Test plan com 15 testes futuros obrigatórios.
- Fases MC0–MC7 e 16 issues de backlog (MC-001…MC-016).

## 6. O que NÃO foi implementado

- Sem código funcional (nenhum arquivo em `src/nomos/council/`).
- Sem CLI real (nenhum `nomos conselho …`).
- Sem chat command real (nenhum `/conselho`).
- Sem alteração de motores, roteador, agentes, skills, audit log ou vault.
- Sem PyPI.
- Sem GitHub Release.
- Sem criação/movimentação de tags.
- Sem force-push.

## 7. Riscos de implementação futura

- **Custo/latência**: rodar N candidatos + M juízes localmente pode ser pesado;
  o modo rápido e o fallback de motor único existem para conter isso.
- **Qualidade dos juízes locais**: modelos pequenos podem julgar mal; mitigar
  com rubrica estruturada, diversidade e o veto do árbitro + gate.
- **Vazamento de autoria**: a anonimização precisa ser testada de fato
  (`test_council_anonymizes_candidates`) — é o ponto mais fácil de errar.
- **Superfície de prompt injection** cresce com mais motores; o envelopamento
  de conteúdo recuperado (prompt_guard) deve ser aplicado em cada gerador.
- **Persistência acidental em modo privado**: exige teste que inspeciona o FS,
  como já feito para conversas e âncora.

## 8. Próximo passo recomendado

Iniciar a **Fase MC1 (data models only)** sob `implementation-loop-100`: criar
`src/nomos/council/models.py` e testes de schema **sem execução de motores e sem
persistência**, mantendo a suíte verde e o CI nos três sistemas.
