# NOMOS v1.3.0rc4 — Motor Council Dry-run

## Status

```text
PREPARED_ONLY=true
TAG_CREATED=false
RELEASE_PUBLISHED=false
PYPI_PUBLISHED=false
```

Este documento é um **rascunho de release notes**, preparado na Fase MC10
(Documentation Index + RC4 Preparation). Nenhuma tag, GitHub Release ou
publicação no PyPI foi criada por este documento. A versão empacotada
(`pyproject.toml` / `src/nomos/__init__.py`) permanece `1.3.0rc16` nesta fase
— o número `v1.3.0rc4` acima se refere ao **release público planejado**
(numeração de release, diferente da numeração interna `rcNN` incremental de
pacote usada a cada fase MC).

## Summary

Consolida o **Motor Council** — o pipeline de múltiplos motores que revisa,
julga e arbitra respostas antes do envio ao usuário — em estado **dry-run
completo e auditável**: modelos de dados puros, simulador offline
determinístico, contrato de provedor de candidatos locais, adaptador de
motor local em SPEC/DRY-RUN, harness de execução real travado
(`REAL_LOCAL_ENGINE_EXECUTION_ENABLED = False`), integração dry-run com o
Policy Gate A0–A6, envelope de auditoria dry-run metadata-only, um
orquestrador que compõe tudo isso num único fluxo em memória, e uma
especificação completa de UX futura para `nomos conselho` (CLI) e
`/conselho` (chat) — ainda sem implementar nenhum comando real.

Nove fases (MC1–MC9) foram entregues sob disciplina
`implementation-loop-100` (SPEC → IMPLEMENTAR → TESTAR → VALIDAR →
EVIDENCIAR → ENTREGAR), cada uma com baseline verde antes e depois, CI 17/17
em três sistemas operacionais, e prova de segurança por análise AST (não por
convenção).

## Security Guarantees

- No real engine execution.
- No cloud.
- No network.
- No subprocess.
- No real policy.
- No real audit.
- No real vault.
- No real approval.
- Private mode disables persistence.
- Gate required before final envelope.
- Audit envelope is metadata-only.

## Tests

```text
PYTEST=778
```

Progressão: 520 (baseline MC0) → 551 (MC1) → 577 (MC2) → 608 (MC3) → 637
(MC4) → 663 (MC5) → 693 (MC6) → 724 (MC7) → 778 (MC8) → 778 (MC9, docs-only).
Nenhum teste foi removido ou enfraquecido em nenhuma fase.

## CI

17/17 esperado após MC10 (ver `docs/missions/
MOTOR_COUNCIL_MC10_DOCUMENTATION_INDEX_RC4_PREP.md` para o commit final e a
confirmação real de CI desta fase). Todas as fases MC1–MC9 anteriores
fecharam com CI 17/17 confirmado via API do GitHub (12 jobs de teste × 3 SOs
× 4 versões de Python, mais cobertura informativa, mypy informativo e smoke
pós-instalação do wheel em 3 SOs).

## What's Included

- `nomos.council.models` — modelos de dados puros com invariantes de
  segurança por construção (MC1).
- `nomos.council.simulator` — simulador offline determinístico (MC2).
- `nomos.council.local_provider` — contrato de provedor de candidatos locais
  (MC3).
- `nomos.council.local_adapter` — adaptador de motor local em SPEC/DRY-RUN,
  `would_execute=false` sempre (MC4).
- `nomos.council.local_harness` — harness de execução real, travado por
  constante literal `False`, sem API de ativação (MC5).
- `nomos.council.policy_gate` — integração dry-run com o Policy Gate A0–A6
  (MC6).
- `nomos.council.audit_envelope` — envelope de auditoria dry-run,
  metadata-only, `private_mode` ⇒ `persist_allowed=false` (MC7).
- `nomos.council.orchestrator` — orquestrador que compõe as sete peças acima
  num único fluxo determinístico e fail-closed de ponta a ponta (MC8).
- `docs/architecture/MOTOR_COUNCIL_UX_SPEC_v1.md` — especificação de UX
  futura para CLI (`nomos conselho`) e chat (`/conselho`) (MC9).
- `docs/architecture/MOTOR_COUNCIL_INDEX_v1.md` — índice técnico
  consolidando MC0–MC9 (MC10).

## Not Included

- No real CLI.
- No real chat command.
- No real engine.
- No PyPI.
- No production release.
- No tag on this repository yet.

## Next Step

Próximo passo recomendado (não iniciado por este documento): **MC11 — RC4 Tag
Preparation/Validation**, com validação de CI e ancestry antes de criar a
tag `v1.3.0rc4`, ainda sem publicar GitHub Release automaticamente.
