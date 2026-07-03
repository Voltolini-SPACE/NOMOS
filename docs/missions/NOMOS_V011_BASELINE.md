# NOMOS V0.11 — Baseline (Fase 0)

Data: 2026-07-03 · Auditoria feita sobre `main` (aad7ee0) · Versão atual: 0.10.0

## Resumo da arquitetura

```
src/nomos/
├── cli.py            # superfície argparse; fail-closed; exit codes 0/1/3
├── kernel/           # governança
│   ├── policy.py     # taxonomia A0–A6, PolicyEngine fail-closed, gate()
│   ├── localidade.py # cadeado só-local (padrão LIGADO), DENY de egress não-loopback
│   ├── vault.py      # cofre cifrado (Argon2id/PBKDF2), arquivo 0600
│   ├── audit.py      # cadeia de hash + redação de segredos (chaves e padrões)
│   ├── consent.py    # consentimento com TTL p/ mic/câmera/tela
│   ├── approvals.py  # fila de aprovações p/ painel local
│   ├── config.py     # NOMOS_HOME, agent.json
│   └── plataforma.py # chmod portável, detecção de SO
├── cognition/
│   ├── router.py     # local-first; cloud exige A2+A3; modo degradado honesto
│   ├── motores.py    # detecção por modalidade (texto/codigo/imagem/audio)
│   ├── providers.py  # Ollama local + Anthropic (opt-in)
│   ├── embutido.py   # cérebro leve llama.cpp + catálogo de modelos
│   ├── memory.py     # SQLite + FTS5
│   └── criacao.py    # imagem (SD-WebUI) e voz (piper), com gates
├── ext/
│   ├── skills.py     # instalação governada: manifesto+checksum+gate
│   └── signing.py    # ed25519, TrustStore, pin TOFU
├── runtime/          # sandbox com isolamento de rede (fail-closed sem netns)
├── interface/panel.py# painel local de aprovações
└── simple/           # UX pt-BR: onboarding, chat amigável, doutor, chaves, tema
```

## Estado dos testes (baseline)

- `python -m pytest -q` → **246 passed** (12.7s), 0 falhas.
- `ruff check src tests` → **All checks passed**.
- Cobertura: não configurada (sem pytest-cov no projeto); não adicionada para
  não mudar o perfil de dependências.

## Comandos existentes

`start`, `cerebro (status|instalar|baixar)`, `doutor`, `tema`, `local (status|on|off)`,
`chaves (listar)`, `motores (listar|usar)`, `init`, `agent create`, `vault
(init|set|get|list|rotate)`, `consent (status|grant|revoke)`, `panic`, `run`,
`skill (install|keygen|sign|trust add|trust revoke|list|remove)`,
`approvals (serve|list)`, `chat`, `memory (...)`, `status`, `logs verify`.

`nomos` sem comando: TTY → chat simples (com onboarding na 1ª vez); sem TTY → help.

## Políticas vigentes

- **Localidade**: padrão LIGADO; ausência/corrupção do arquivo ⇒ LIGADO.
  Egress não-loopback vira `DENY` na própria política (antes do gate).
- **Aprovação**: A0 ALLOW; A1–A5 REQUIRE_APPROVAL; A6 DENY. Gate sem aprovador
  ⇒ nega. Aprovador interativo exige TTY + palavra exata ("APROVO"/"sim").
- **Segredos**: audit redige por nome de campo e padrão de valor; vault 0600;
  sandbox não herda env do host.

## Motores e skills hoje

- Motores: 4 modalidades (texto/codigo/imagem/audio), detecção com cache 10s,
  escolha persistida no perfil, honestidade quando falta motor. Sem roteador
  automático por tarefa, sem custo/privacidade/qualidade na tabela.
- Skills: instalação com manifesto v1 (name/version/permissions/entry/files),
  checksum, assinatura opcional ed25519 + trust + TOFU. Sem: registry local,
  estado ativa/inativa, risco, execução governada, menu amigável.

## Riscos encontrados

1. README menciona instaladores/release e wheel 0.10.0 — não há `docs/` no
   repositório; desalinhamento documentação × código (Fase 8 corrige).
2. Não há execução de skill governada — instalar existe, rodar não; permissões
   declaradas ainda não são verificadas em uso (Fase 2 corrige).
3. `nomos` sem comando cai direto no chat; iniciante não descobre skills,
   motores e doutor (Fase 6 corrige).
4. Doutor não emite STATUS GERAL nem próximo passo único acionável (Fase 7).
5. Roteamento é só texto local→cloud; não considera modalidade, custo,
   contexto, sensibilidade (Fases 3–5).

## Pontos de extensão recomendados

- `cognition/motores.py` já expõe `detectar()/ativo()` — o catálogo v0.11
  consome isso sem tocar na detecção.
- `kernel/policy.py:gate()` é a única porta de aprovação — roteador, pipeline
  e execução de skill passam por ela (nenhum caminho novo de autorização).
- `simple/*` usa `ask=input, say=print` injetáveis — novos menus seguem o
  mesmo padrão (100% testáveis sem TTY).
- Perfil (`agent.json` via `salvar_perfil`) guarda escolhas de motor; recebe
  também `motores_auto` (roteador automático) e nada mais sensível.

## Arquivos que serão alterados/criados

| Ação | Arquivo |
|---|---|
| criar | `src/nomos/ext/skill_registry.py`, `src/nomos/ext/skill_status.py` |
| criar | `src/nomos/simple/skills_menu.py`, `src/nomos/simple/menu_principal.py` |
| criar | `src/nomos/cognition/engine_catalog.py`, `engine_policy.py`, `engine_router.py`, `engine_pipeline.py` |
| editar | `src/nomos/cli.py` (novos subcomandos; compat preservada) |
| editar | `src/nomos/simple/doutor.py` (STATUS GERAL + próximo passo) |
| editar | `src/nomos/__init__.py`, `pyproject.toml` (0.11.0), `README.md` |
| criar | `docs/` (INSTALL, MOTORES, SKILLS, ROTEADOR, PRIVACIDADE, USUARIO_INICIANTE, CHANGELOG) |
| criar | `tests/test_skills_menu.py`, `test_skill_registry.py`, `test_engine_catalog.py`, `test_engine_router_auto.py`, `test_engine_pipeline.py`, `test_motores_ux.py`, `test_doutor_v011.py`, `test_local_first_regression.py`, `test_no_secret_leak_regression.py`, `test_cloud_opt_in_regression.py` |

## Plano incremental

1. Fases 1–2: registry/status/menu de skills + execução governada (`nomos skills`).
2. Fases 3–4: catálogo v0.11 (12 modalidades) + roteador automático local-first.
3. Fase 5: pipeline de motores com política em cada etapa.
4. Fases 6–7: menu principal amigável + doutor com STATUS GERAL.
5. Fases 8–9: documentação real + suíte de testes obrigatória.
6. Fase 10: verificação de aceite + relatório final.

Nenhuma refatoração dos módulos do kernel; somente adições e fiação na CLI.
