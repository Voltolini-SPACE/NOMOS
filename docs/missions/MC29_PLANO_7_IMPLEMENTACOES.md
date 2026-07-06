# MC29 — Plano Profissional: as 7 Implementações (execução completa)

**Data:** 2026-07-05 · **Origem:** plano da missão de validação ponta a ponta
(`MC_VALIDACAO_PONTA_A_PONTA_NOMOS.md`, §11) · **Skill:** implementation-loop-100
**Ordem executada:** 7 → 6 → 4 → 5 → 2 → 3 → 1 (fundação de política primeiro,
painel por último consumindo o que ficou pronto).

| # | Implementação | Commit | Entregas | Testes novos |
|---|---|---|---|---|
| 7 | Política formal de segurança | `1e4322a` | `docs/governance/SECURITY_POLICY.md` (SEC-01…SEC-12) + contrato executável | 13 |
| 6 | Brand + Site Sync Agent | `5d4f8d2` | update agent MC29.0: 4 checks de marca no gate CI; testes MC27 desfragilizados | 8 |
| 4 | Sistema de evidências | `890a41f` | `kernel/evidencia.py` + `nomos evidencia criar/verificar` (pacote redigido, verificável offline) | 9 |
| 5 | Git Agent seguro | `bc46a3b` | `tools/nomos_git_agent.py` (--check/--suggest/--handoff; allowlist de leitura; sem push por contrato) | 10 |
| 2 | Roteador explicável | `eb6ad91` | `relatorio_decisao()` + `nomos motores recomendar <mod> --json` (trace completo; `rotear()` intacto) | 7 |
| 3 | Catálogo de capacidades | `58d22c8` | `ext/skill_catalogo.py` + `nomos skills catalogo [--json]` (8 campos, risco visível) | 7 |
| 1 | Painel web evoluído | `5e5ba5a` | seções Evidências (integridade real) e Política A0–A6 viva; loopback/read-only preservados | 4 |

**Total: 58 testes novos (suíte: 1139 → 1197).** Cada implementação foi um ciclo loop-100 completo
(spec → implementar → testar → validar → commit), sempre com ruff limpo e as
suítes vizinhas re-executadas (roteador/local-first, painel v0.17, MC25–27).

## Princípios preservados (provados por teste)

- Execução real do council continua **desligada** (SEC-01); dry-run é default.
- Nenhum agente novo é capaz de push/commit/deploy — push é decisão humana.
- Todas as saídas novas são redigidas ou metadados; segredos nunca aparecem.
- Local-first intacto: cadeado de localidade explicado no trace do roteador.
- Nada quebrou: contratos antigos (`rotear`, painel, update agent --check/
  --diff) verificados por igualdade/suíte de regressão.

## Próxima missão recomendada

1. **CI**: adicionar `nomos_git_agent --check --json` como segundo gate read-only.
2. **Release**: taggear `v1.3.0rc17` (ou promover rc) com changelog consolidado.
3. **Painel**: link "abrir evidência" (servir RELATORIO.md do pacote, ainda read-only).
4. **Arbitragem**: runners reais opcionais (Ollama) atrás do gate de aprovação.
