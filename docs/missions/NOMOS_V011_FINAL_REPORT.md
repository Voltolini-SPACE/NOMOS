# NOMOS V0.11 — Relatório Final

Data: 2026-07-03 · Baseline: [NOMOS_V011_BASELINE.md](NOMOS_V011_BASELINE.md)
Versão entregue: **0.11.0**

## O que foi implementado

### Fases 1–2 — Skills amigáveis + registry local
- Grupo `nomos skills` (o técnico `nomos skill` permanece intacto): `menu`,
  `listar`, `instalar`, `remover`, `info`, `ativar`, `desativar`, `rodar`,
  `diagnostico`. Sem TTY, `skills`/`skills menu` degradam para `listar`.
- Manifesto v2 com padrões seguros e compat v1 total: description, entrypoint,
  risk_level, requires_approval, publisher, compatible_nomos_version,
  modalities, local_only_capable, cloud_required. Risco é **calculado** das
  permissões (desconhecida ⇒ alto) e o manifesto não consegue se declarar
  menos exigente que o cálculo.
- Estados por skill: ativa / inativa / quebrada (checksum, entry ou manifesto)
  / confiável (assinatura+trust) / experimental (não assinada ou risco alto,
  exige digitar `ACEITO O RISCO` em TTY; em CI é negada).
- Registry local: `~/.nomos/registry/catalogo.json` — skill *disponível* ≠
  *instalada*; catálogo corrompido ⇒ vazio (fail-closed).
- **Execução governada** (`skills rodar`): somente permissões declaradas,
  categoria a categoria pelo `gate()`; rede ⇒ A2 (cai no cadeado só-local);
  entry roda no sandbox; skill desativada/quebrada não roda; auditoria guarda
  metadados (nunca o stdout da skill).

### Fases 3–4 — Motores + roteador automático
- `engine_catalog`: 12 modalidades (texto, codigo, raciocinio, resumo,
  memoria, voz_stt, voz_tts, imagem, visao, embeddings, ferramentas,
  roteamento) sobre a detecção existente; atributos: local/nuvem, instalado,
  pronto, custo, privacidade, velocidade, qualidade, requer chave, requer
  aprovação, status.
- `engine_policy`: elegibilidade com motivo honesto; nuvem exige cadeado
  aberto + chave (checada por NOME, sem ler valor) e sempre marca
  `exige_aprovacao`; dados sensíveis vetam nuvem mesmo plugada; modo
  automático persistido no perfil (padrão ligado).
- `engine_router`: `EngineRouteDecision` completo (selected/fallback/reason/
  privacy/approval/cost/local_only_preserved/confidence/steps); regras 1–7 da
  missão implementadas; sem motor ⇒ diagnóstico acionável, nunca inventa;
  classificador heurístico transparente (sem IA decidindo rota).
- CLI: `nomos motores menu|listar|status|recomendar|auto on/off|testar|
  diagnostico` — e `nomos motores`/`usar` idênticos ao v0.10.

### Fase 5 — Pipeline de motores
- `EnginePipeline`/`PipelineStep`/`PipelineResult`/`PipelineAudit`: cada etapa
  passa pela política; primeira negação/erro para tudo; aprovador com erro
  nunca autoriza; auditoria filtra conteúdo (só metadados); explicação
  simples ("Usei: X → Y. Nada saiu da sua máquina.").

### Fases 6–7 — UX + doutor
- `nomos` (configurado, em TTY) abre menu principal com as 10 opções da
  missão; 1ª vez segue para onboarding; sem TTY mostra ajuda (como antes).
  Erros de ação não derrubam o menu nem despejam traceback.
- Doutor v0.11: `STATUS GERAL: PRONTO/PARCIAL/BLOQUEADO`, checa Python, home,
  agente, localidade, cofre/chaves, auditoria (violada ⇒ BLOQUEADO), cérebro,
  motores por modalidade, skills (inclusive quebradas) e recomenda **um**
  próximo passo. Funções v0.10 (`diagnostico`, `texto_relatorio`) intactas.

### Fase 8 — Documentação
- Novos: `docs/INSTALL.md`, `docs/MOTORES.md`, `docs/SKILLS.md`,
  `docs/ROTEADOR.md`, `docs/PRIVACIDADE.md`, `docs/USUARIO_INICIANTE.md`,
  `CHANGELOG.md`, `docs/missions/` (baseline + este relatório).
- README alinhado à realidade: instalação por código como caminho suportado,
  instaladores descritos como planejados (base em `installer/`), comandos
  novos, "o que o NOMOS nunca faz", status de maturidade.

## Arquivos alterados/criados

Criados: `src/nomos/ext/skill_registry.py`, `src/nomos/ext/skill_status.py`,
`src/nomos/simple/skills_menu.py`, `src/nomos/simple/menu_principal.py`,
`src/nomos/cognition/engine_catalog.py`, `engine_policy.py`,
`engine_router.py`, `engine_pipeline.py`, 7 documentos, 8 suítes de teste.
Editados: `src/nomos/cli.py` (novos subcomandos + menu principal),
`src/nomos/simple/doutor.py` (v0.11 aditivo), `README.md`,
`src/nomos/__init__.py` e `pyproject.toml` (0.11.0).
Nenhum arquivo do kernel (`policy`, `vault`, `audit`, `localidade`,
`consent`, `sandbox`, `signing`, `skills.py`) foi modificado.

## Comandos novos

`nomos skills [menu|listar|instalar|remover|info|ativar|desativar|rodar|
diagnostico]` · `nomos motores [menu|status|recomendar|auto on/off|testar|
diagnostico]` · `nomos` ⇒ menu principal (após onboarding).

## Testes

| Suíte | Cobre |
|---|---|
| test_skill_registry.py | risco, manifesto v2, catálogo, execução governada |
| test_skills_menu.py | status ativa/inativa/quebrada, permissões, diagnóstico |
| test_engine_catalog.py | 12 modalidades, atributos, nuvem × cadeado |
| test_engine_router_auto.py | regras 1–7, classificador, auto on/off |
| test_engine_pipeline.py | política por etapa, parada honesta, auditoria |
| test_motores_ux.py | CLI de motores nova + compat |
| test_doutor_v011.py | STATUS GERAL, próximo passo, auditoria violada |
| test_menu_principal_v011.py | menu de 10 opções, resiliência, sem TTY |
| test_local_first_regression.py | cadeado padrão, DENY de egress, roteador |
| test_no_secret_leak_regression.py | segredo fora de stdout/log em caminhos novos |
| test_cloud_opt_in_regression.py | A2+A3, CI nega, chave por nome |

**Resultado: 340 passed (246 do baseline + 94 novos), 0 falhas. `ruff check
src tests`: limpo.** Cenários obrigatórios 1–13 da Fase 9: todos cobertos.

## Critérios de aceite (Fase 10)

pytest 100% ✅ · ruff ✅ · comandos antigos idênticos ✅ · comandos novos ✅ ·
`nomos` fluxo simples ✅ · `skills menu` ✅ · `motores menu` ✅ ·
`motores recomendar` ✅ · doutor acionável ✅ · roteador local-first ✅ ·
nuvem só com opt-in ✅ · skill sensível só com gate ✅ · auditoria íntegra ✅ ·
README/docs reais ✅ · relatório final ✅

## Garantias preservadas (verificadas por teste)

Local-first por padrão (ausência/corrupção ⇒ ligado); fail-closed em política,
gate, catálogo de skills e roteador; zero segredo em stdout/log (redação por
campo e padrão, auditoria de pipeline/skill só com metadados); nenhuma cloud
sem opt-in consciente + aprovação por uso; nenhum bypass novo — roteador e
pipeline **decidem**, quem autoriza continua sendo o único `gate()`;
CI/non-interactive nega tudo sensível; compatibilidade total com v0.10.

## Riscos pendentes

1. Release/instaladores de um clique ainda não publicados no GitHub — README
   agora é honesto sobre isso; publicar é passo operacional (fora do código).
2. Execução de skill depende do sandbox com isolamento de rede; em Mac/Windows
   sem namespaces ele recusa rodar (fail-closed) — comportamento correto, mas
   vale documentar alternativas de isolamento por plataforma no futuro.
3. O classificador de tarefas é heurístico simples (transparente por design);
   casos ambíguos caem em "texto" — evolução natural: sinais do usuário.
4. Catálogo local de skills começa vazio; a experiência "marketplace" plena
   depende de publicadores assinarem e distribuírem catálogos.

## Próximas fases recomendadas

1. **v0.12 — Release real**: publicar wheel + instaladores (base `installer/`),
   assinatura de artefatos, `SHA256SUMS` na release do GitHub.
2. **Voz de ponta a ponta**: pipeline pronto (STT→resumo→memória) exposto no
   chat (`/ouvir`), usando whisper/piper quando presentes.
3. **Catálogo assinado**: formato de catálogo com assinatura de publicador e
   atualização opt-in (nunca automática).
4. **Roteador com aprendizado local**: registrar (localmente) qualidade
   percebida por motor para refinar `confidence` — sem telemetria.
5. **Painel local**: estender o painel de aprovações para mostrar decisões do
   roteador e diagnóstico do doutor.
