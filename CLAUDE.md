# NOMOS — contexto do projeto (lido automaticamente pelo agente)

## O que é
NOMOS é um agente pessoal de IA 100% local ("local por lei"). Python 3.10+,
repo `Voltolini-SPACE/NOMOS`. Código em `src/`, testes em `tests/`, site em
`site/`, docs em `docs/`.

## Regras invioláveis (herdadas do ROADMAP_4 §1)
1. Local-first; níveis A0–A6 fail-closed; aprovação humana para tudo sensível.
2. **Push e publicação são humanos.** Agente nunca faz `git push`, PR, merge
   ou tag. Trabalho fica em branch local, commitado, pronto para revisão.
3. Nunca commitar direto na `main`.
4. Evidência por missão: toda mudança nasce com teste + entrada no CHANGELOG.
5. REGRA MC33: o site sempre reflete o produto.
6. Componente AGPL nunca linkado (só processo externo).

## Como trabalhar aqui
- Método: **loop-100** (SPEC → IMPLEMENTAR → TESTAR → VALIDAR → EVIDENCIAR →
  ENTREGAR). Missões nomeadas em ciclos MC; relatórios em `docs/missions/`.
- Validar sempre: `python -m pytest -q` e `ruff check .` — ambos 100% limpos
  antes de qualquer commit.
- CHANGELOG: formato Keep a Changelog, pt-BR, seção `[Unreleased]`, datas UTC.
- Commits: convencionais (`feat(escopo): ...`, `fix: ...`, `docs(repo): ...`).

## Sistema de loop autônomo
O loop de desenvolvimento contínuo vive em `loop/`:
- `loop/LOOP_PROMPT.md` — o protocolo que cada rodada executa.
- `loop/BACKLOG.md` — fila de missões (o que fazer).
- `loop/LOOP_LOG.md` — estado + diário (o que foi feito; a próxima rodada lê antes de agir).
- `loop/CONECTORES.md` — integrações (git local hoje; GitHub/Slack opcionais).
- Sub-agentes em `.claude/agents/`: `nomos-executor` (escreve) e
  `nomos-revisor` (confere; read-only). Quem escreve nunca se auto-aprova.
