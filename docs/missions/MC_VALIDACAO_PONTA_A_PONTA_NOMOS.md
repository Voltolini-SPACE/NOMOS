# MC — VALIDAÇÃO PONTA A PONTA DO NOMOS (diagnóstico read-only)

**Data:** 2026-07-05 · **Executor:** Claude (Cowork) · **Skill:** implementation-loop-100
**Modo:** SOMENTE DIAGNÓSTICO (decisão do operador — sessão concorrente ativa no repo)
**Destino sugerido deste arquivo:** `docs/missions/MC_VALIDACAO_PONTA_A_PONTA_NOMOS.md`

---

## 0. Contexto operacional decisivo

Durante o baseline foi detectada **outra sessão editando o repositório em tempo real**
(mtimes de `src/nomos/cli.py` 20:48:56, `tests/test_arbitragem.py` 20:49:30, novos
arquivos surgindo durante a missão — missões ARBITRAGEM e SITE_EXPAND). O operador
escolheu: **"Só diagnóstico, sem escrita"**. Consequência: nenhum byte do repo foi
alterado; todas as correções foram entregues como **patches validados** + arquivos
prontos para aplicar, no pacote de outputs desta sessão. Toda a execução de testes
ocorreu em **snapshots isolados** (`/tmp/nomos_snap`, `/tmp/nomos_head`) para não
interferir no trabalho concorrente.

## 1. Baseline inicial

| Item | Valor |
|---|---|
| Repo real | `NOMOS_REPO/nomos` (a pasta `NOMOS_REPO` é invólucro com artefatos soltos, sem `.git`) |
| Branch | `main` |
| HEAD | `d96e96a` — "docs(repo): changelog MC25–MC27 e relatório de consolidação MC28" (2026-07-05 13:09 -0300) |
| Remote | `origin = github.com/Voltolini-SPACE/NOMOS` · `git rev-list origin/main...HEAD` = **0 0** (sincronizado) |
| Tags | 6 (última: `v1.3.0rc4-motor-council-dry-run`) — **versão do pyproject 1.3.0rc16 ainda sem tag** |
| Working tree | 4 modificados + 4-5 não rastreados = **WIP da sessão concorrente** (arbitragem + site expand) |
| Versão | pyproject `1.3.0rc16` == `nomos.__version__` ✔ |
| Suíte | 1114 testes no HEAD; 1121+ com WIP |
| Push executado | **NO** (proibido pela missão; nada foi commitado) |

## 2. Arquivos e áreas inspecionados

`README.md` (153 l) · `CHANGELOG.md` (871 l, atualizado até MC27) · `pyproject.toml` ·
`conftest.py` · `.gitignore` · `.github/workflows/{ci,release}.yml` ·
`docs/brand/NOMOS_BRANDBOOK.md` + `docs/brand/frozen/*` (hashes) ·
`docs/installation/NOMOS_INSTALLATION_MANUAL.md` (602 l) · `docs/governance/NOMOS_UPDATE_AGENT.md` ·
`site/{index.html,404.html,README.md,preview.py,assets/}` · `src/nomos/**` (82 módulos:
kernel, council, cognition, agents, ext, interface, runtime, simple) · `tests/` (75+
arquivos) · `tools/nomos_update_agent.py` · `installer/` · WIP: `ARBITRAGEM_SPEC.md`,
`arbitragem.py`, `test_arbitragem.py`, `SITE_EXPAND_FULL_CAPABILITIES.md` ·
artefatos do invólucro (`MC24_HANDOFF/`, `Atlas.app`, wheel/tar/bundle v0.10.0, etc.).

### Tabela de inspeção

| Área | Estado | Problemas | Ação recomendada |
|---|---|---|---|
| Código `src/` | ✅ Excelente | ruff 100% limpo (src+tests+tools, incl. WIP) | — |
| Testes | ✅ Fortes | 1114 no HEAD; suíte roda em ~24 s | aplicar suíte anti-regressão nova |
| Git | ✅ Saudável | WIP não commitado; rc16 sem tag | commitar WIP ao terminar; taggear rc |
| CI | ✅ | 3 SOs × py3.10–3.13; release com gate lint+testes | — |
| README | ⚠️ | "884 testes" desatualizado (HEAD tem 1114) | patch 0001 |
| Manual instalação | 🔴 | recomenda `pip install nomos` (pacote de TERCEIROS no PyPI) | patch 0002 |
| Brandbook expandido | ⚠️ | mesma recomendação `pip install nomos` (§5) | patch 0003 |
| Brandbook congelado | ✅ | `sha256sum -c` → 4/4 OK | — |
| Site | ⚠️ WIP | `index.html:354` também recomenda `pip install nomos` | patch 0004 (após WIP) |
| docs/INSTALL.md | ⚠️ menor | exemplo com wheel `0.12.0` (atual: 1.3.0rc16) | atualizar exemplo |
| pyproject urls | ❓ | `Changelog` aponta `blob/main/nomos/CHANGELOG.md` (layout suspeito) | ver NAO_VALIDADO |
| Invólucro NOMOS_REPO | ⚠️ | artefatos históricos soltos fora do git | arquivar (ver §4) |

## 3. Problemas encontrados (com evidência)

1. **[ALTO — segurança de cadeia de suprimentos na documentação]** `pip install nomos`
   é recomendado como caminho oficial no manual (l.65, 300, 303, 326, 370, 576), no
   brandbook expandido (l.240) e no site WIP (`index.html:354`). **Evidência:**
   `pypi.org/project/nomos` = *"nomos 0.3.7 — Configurable multi-step agent framework"*,
   autor dowhiledev/chandralegend — **projeto de terceiros**. Quem seguir o manual instala
   outro software. Correção proposta: `pip install git+https://github.com/Voltolini-SPACE/NOMOS`
   + aviso explícito (patches 0002/0003/0004) + teste de contrato que impede regressão.
2. **[MÉDIO — coerência]** README §Maturidade afirma "Suíte com 884 testes"; HEAD tem
   1114 (o próprio CHANGELOG registra "Suíte: 1024 → 1114"). Patch 0001 troca por
   "mais de 1.100" (sem número exato — não recongela o problema).
3. **[BAIXO]** `docs/INSTALL.md:49` usa wheel `nomos-0.12.0` como exemplo (versão atual
   1.3.0rc16). Sugerido: exemplo sem versão fixa ou com placeholder `<versão>`.
4. **[BAIXO]** Versão `1.3.0rc16` (pyproject) sem tag correspondente (última tag rc4).
   Não é bug — mas convém taggear quando o WIP estabilizar.
5. **[INFO — WIP]** `tests/test_arbitragem.py::test_cli_arbitrar_honesto_no_sandbox`
   falha no repo real (AssertionError l.208) — é o teste do trabalho **em andamento**
   da sessão concorrente (CLI `arbitrar` sendo escrita). Não é regressão do HEAD.

**Não encontrados:** secrets hardcoded (grep em src/tools/installer = 0); `eval`/`exec`
(0 em src); código morto com evidência (ruff F-rules limpos); import quebrado (suíte
importa 100% com PYTHONPATH); `rm -rf` fora de uninstaller/rollback/docs (escopados a
`$PREFIX`/`~/.nomos`).

## 4. Ruídos classificados

```
RUÍDOS_CLASSIFICADOS:
- remover (lixo local, já git-ignorado; apagar é opcional e seguro):
    nomos/.coverage, .pytest_cache/, .ruff_cache/, __pycache__/ (raiz e tools/),
    build/, dist/.tmp-*/, UNKNOWN.egg-info/, nomos-1.3.0rc16/ (extração de sdist),
    NOMOS_REPO/.DS_Store, NOMOS_REPO/.__deltest, NOMOS_REPO/.tmp-2pms03sw
- ignorar (já cobertos): git check-ignore validou 10/10 padrões — .gitignore saudável
- arquivar (histórico; mover p/ NOMOS_REPO/archive/, fora do git):
    MC24_HANDOFF/ (patches+bundles MC24–MC28), PUBLICADO.md, PUBLICAR_NO_GITHUB.md,
    RELATORIO_FINAL.md, SHA256SUMS (raiz), nomos-0.10.0-py3-none-any.whl,
    nomos-repo-v0.10.0.tar.gz, nomos.bundle (era v0.10.0)
- revisar depois:
    Atlas.app + COMO_USAR_ATLAS.md (produto derivado; decidir lar definitivo),
    docs/INSTALL.md exemplo 0.12.0, pyproject [project.urls].Changelog,
    UNKNOWN.egg-info (indica build antigo sem metadados — investigar origem 1×)
- manter: todo o resto (inclusive 100% do WIP da sessão concorrente — intocado)
```

Nada foi apagado nesta missão (modo diagnóstico).

## 5. Grep de padrões perigosos — classificação

| Padrão | Ocorrências | Classificação |
|---|---|---|
| `subprocess` | `runtime/sandbox*.py`, `cognition/{arquivos,criacao,embutido}.py` | **seguro/esperado** — sandbox e binários locais (whisper, pip do cérebro), com timeout; council só cita em docstrings de pureza |
| rede (`urllib`) | `cognition/{motores,providers,criacao,visao,embutido}.py`, `simple/atualizar.py` | **seguro** — esquema http/https validado, loopback validado (visão), `# nosec B310` justificado; opt-in de nuvem |
| `eval(`/`exec(`/`os.system` | 0 em `src/` | ✅ |
| secrets hardcoded | 0 | ✅ |
| `rm -rf` | `installer/{uninstall,rollback}.sh`, manuais | **esperado** — escopado a `$PREFIX`/`~/.nomos` |
| Trava execução real | `local_harness.REAL_LOCAL_ENGINE_EXECUTION_ENABLED = False` (literal, exportada) | ✅ confirmada + já coberta por testes de segurança existentes |

## 6. Mudanças implementadas (como PROPOSTAS — repo intocado)

| Entrega | Arquivo (outputs) | Motivo | Risco | Teste | Rollback |
|---|---|---|---|---|---|
| Patch README | `patches_propostos/0001-readme-contagem-testes.patch` | contagem desatualizada | nulo | `git apply --check` OK | `git checkout README.md` |
| Patch Manual | `patches_propostos/0002-manual-pypi-colisao-nome.patch` | colisão PyPI | baixo | `git apply --check` OK + 6/6 verdes pós-patch | `git checkout` |
| Patch Brandbook | `patches_propostos/0003-brandbook-pypi-colisao-nome.patch` | idem (§5) | baixo | idem | idem |
| Patch Site | `patches_propostos/0004-site-pypi-colisao-nome.APOS-WIP.patch` | idem (l.354) | **aplicar só após o WIP do site estabilizar** (pode não aplicar limpo) | validado na cópia | idem |
| Suíte anti-regressão | `test_missao_validacao_anti_regressao.py` → `tests/` | blindar 6 contratos | nulo (aditivo) | 6/6 pós-patches; 5/6 antes (falha proposital no contrato do pip) | remover arquivo |

Como aplicar (quando o WIP terminar e você aprovar):

```bash
cd <repo>/nomos
git apply <outputs>/patches_propostos/0001-readme-contagem-testes.patch
git apply <outputs>/patches_propostos/0002-manual-pypi-colisao-nome.patch
git apply <outputs>/patches_propostos/0003-brandbook-pypi-colisao-nome.patch
cp <outputs>/test_missao_validacao_anti_regressao.py tests/
# site: aplicar 0004 OU corrigir a linha na missão do site
python -m pytest -q && python -m ruff check src tests
```

## 7. Testes executados (comando → evidência → resultado)

| # | Comando | Evidência | Resultado |
|---|---|---|---|
| 1 | `pytest -q` no snapshot do working tree (WIP) | `13 failed, 1120 passed in 23.65s` | baseline WIP |
| 2 | `pytest -q` no `git archive HEAD` | `6 failed, 1108 passed in 23.67s` | HEAD quase-verde |
| 3 | subset das falhas no **repo real** (read-only: `-p no:cacheprovider`, `PYTHONDONTWRITEBYTECODE`) | `1 failed, 108 passed in 1.98s` | **as 6 falhas do HEAD-archive eram ambientais** (testes MC25–27 exigem `.git`, que o archive não tem); única falha real = teste WIP de arbitragem |
| 4 | `ruff check src tests tools` | `All checks passed!` | ✅ lint 100% |
| 5 | `sha256sum -c docs/brand/frozen/SHA256SUMS` | 4/4 `OK` | ✅ brandbook congelado íntegro |
| 6 | suíte nova (pré-patch) | `1 failed, 5 passed` — falha exatamente no contrato do pip | prova que o teste captura o problema |
| 7 | suíte nova (pós-patches, na cópia) | `6 passed` | ✅ |
| 8 | suíte completa no snapshot pós-patches | `13 failed, 1126 passed in 23.31s` (mesmas 13 ambientais/WIP; +6 novos verdes) | ✅ zero regressão introduzida |
| 9 | `git apply --check` patches 1–3 no repo real | `OK` ×3 | ✅ aplicam limpo |
| 10 | `mypy` | não configurado no projeto | não executado (conforme missão: não inventar ferramenta) |

Cobertura: não medida nesta sessão (suíte sob timeout do sandbox); disponível via
`pytest --cov` (pytest-cov já é extra `dev` do projeto). Referência histórica: 85% (v0.10).

## 8. Git status final

```
GIT_STATUS_FINAL:
branch=main
head=d96e96a (sincronizado com origin/main, 0 à frente / 0 atrás)
dirty=4 modificados (WIP sessão concorrente: site/index.html, src/nomos/cli.py,
      tests/test_mc25_deliverables.py, tests/test_site_polish.py)
untracked=5 (ARBITRAGEM_MOTORES.md, ARBITRAGEM_SPEC.md, SITE_EXPAND_FULL_CAPABILITIES.md,
      src/nomos/cognition/arbitragem.py, tests/test_arbitragem.py)
remote=origin=https://github.com/Voltolini-SPACE/NOMOS.git
push_executado=NO
alteracoes_por_esta_missao=ZERO (modo diagnóstico)
```

## 9. Validação documental

| Documento | Existe | Atualizado | Coerente | Ação |
|---|---|---|---|---|
| README.md | ✅ | ⚠️ (884) | ✅ resto | patch 0001 |
| CHANGELOG.md | ✅ | ✅ (MC25–27) | ✅ | adicionar entrada desta missão ao aplicar patches |
| Brandbook congelado | ✅ | ✅ (hash OK) | ✅ | — |
| Brandbook expandido | ✅ | ✅ | ⚠️ pip | patch 0003 |
| Manual instalação | ✅ | ✅ | 🔴 pip | patch 0002 |
| Site (index/404/preview) | ✅ (WIP) | em evolução | ⚠️ pip l.354 | patch 0004 pós-WIP |
| Site spec | ✅ (`SITE_EXPAND_FULL_CAPABILITIES.md`, WIP) | ✅ | ✅ | — |
| Missões/handoffs | ✅ 57 docs | ✅ | ✅ | — |
| Update agent (governança) | ✅ | ✅ | ✅ | ampliar checks (plano §11) |

Proposta de entrada no CHANGELOG (colar em `## [Unreleased]` ao aplicar):

```md
### Fixed (MC-VALIDACAO-E2E)
- Docs não recomendam mais `pip install nomos` puro — o nome `nomos` no PyPI é de
  projeto de terceiros; instalação oficial via GitHub/instaladores (README, manual,
  brandbook §5, site). Teste de contrato novo impede regressão.
- README: contagem de testes desatualizada (884 → "mais de 1.100").
### Added (MC-VALIDACAO-E2E)
- `tests/test_missao_validacao_anti_regressao.py`: trava de execução real, hash do
  brandbook congelado, docs essenciais, cobertura do .gitignore, contrato anti
  `pip install nomos`, coerência de versão pyproject↔pacote.
```

## 10. Riscos remanescentes

1. `pip install nomos` permanece nos docs **até os patches serem aplicados** (o risco
   nº 1 continua vivo no repo).
2. WIP concorrente não commitado — perda possível em caso de acidente local; commitar
   assim que a missão de arbitragem/site fechar.
3. `pyproject.urls.Changelog` possivelmente 404 (layout `main/nomos/CHANGELOG.md`).
4. Instaladores (`install.sh/ps1`) não exercitados de ponta a ponta nesta sessão.
5. rc16 sem tag/release — janela onde HEAD e última tag divergem bastante.

```
NAO_VALIDADO:
- item=pyproject.urls.Changelog e visibilidade/layout do repo GitHub
  motivo=fora do sandbox de arquivos; não essencial ao objetivo
  impacto=link possivelmente quebrado em metadados do pacote
  como_validar_depois=abrir https://github.com/Voltolini-SPACE/NOMOS/blob/main/CHANGELOG.md e ajustar a URL
- item=instaladores install.sh/install.ps1 (execução real)
  motivo=executar instalador é ação destrutiva/fora de escopo da missão
  impacto=regressão de instalador não seria detectada aqui
  como_validar_depois=VM descartável: rodar install.sh, `nomos doutor`, uninstall.sh
- item=renderização visual do site
  motivo=site em edição concorrente (WIP)
  impacto=nenhum no código; test_site_polish + preview --check já passam no repo real
  como_validar_depois=`python site/preview.py` após o WIP commitar
- item=cobertura numérica (pytest --cov)
  motivo=janela de 45s do sandbox; suíte+cov excede
  impacto=nenhum funcional
  como_validar_depois=`python -m pytest --cov=nomos -q` local
```

## 11. Plano — 7 implementações profissionais (nível OpenClaw/Hermes, identidade NOMOS)

> Vantagem do NOMOS: quase tudo abaixo já tem embrião no código. O plano é evolução
> com contrato e teste, não big-bang.

**1. Painel Web Local NOMOS (evolução do existente)**
- Objetivo: dashboard loopback-only com status, missões, agentes, motores, dry-runs, evidências, logs e comandos permitidos/bloqueados.
- Por que importa: visibilidade operacional = confiança; é o "rosto" profissional do produto.
- Base real: `src/nomos/interface/painel_web.py` **já é** 127.0.0.1-only e read-only (bind ≠ loopback é recusado). Falta: páginas de missões/evidências/catálogo.
- Arquivos prováveis: `interface/painel_web.py`, `interface/panel.py`, novos templates, `tests/test_painel_*`.
- Risco: baixo (read-only). Testes: bind loopback recusado p/ outros hosts; snapshot HTML das seções; zero escrita.
- Pronto quando: `nomos painel` mostra as 6 seções com dados reais locais, suíte verde.
- Dependências: 4 (evidências) enriquece o painel. Ordem: 6º.

**2. Roteador Automático de Motores — explicável**
- Objetivo: decisão de motor com relatório *por quê* (custo, privacidade, modalidade, disponibilidade) e integração com a arbitragem real (WIP atual).
- Base real: `cognition/{engine_router,engine_policy,engine_catalog,router}.py` + `nomos motores recomendar` já existem; WIP `arbitragem.py` adiciona debate multi-motor.
- Arquivos: `cognition/engine_router.py`, `arbitragem.py` (pós-merge), `tests/test_roteador_explicavel*`.
- Risco: médio (não deixar explicação vazar prompt — reusar `council/safe_output`). Testes: contrato do relatório de decisão; local-first preservado; cloud só opt-in.
- Pronto quando: `nomos motores recomendar <tarefa> --json` retorna decisão + justificativa estável testada.
- Dependências: merge do WIP de arbitragem. Ordem: 4º.

**3. Menu de Skills / Capacidades (catálogo)**
- Objetivo: catálogo navegável nome/descrição/entrada/saída/risco/permissões/status/exemplos.
- Base real: `simple/skills_menu.py`, `ext/skill_*` (manifesto, registry, status, SDK), 4 skills de exemplo em `examples/skills/`.
- Arquivos: `ext/skill_registry.py`, `simple/skills_menu.py`, `tests/test_skills_catalogo*`.
- Risco: baixo. Testes: catálogo lista só skills com manifesto válido; risco sempre exibido; `--json` estável.
- Pronto quando: `nomos skills catalogo [--json]` cobre os 8 campos por skill.
- Ordem: 5º.

**4. Sistema de Evidências e Auditoria (pacote de missão)**
- Objetivo: toda missão gera pacote auditável: relatório, hashes, comandos, diff, status, rollback — como o `MC24_HANDOFF/` fez à mão, mas padronizado e automático.
- Base real: `kernel/audit.py` + `audit_anchor.py` (cadeia de hash + âncora HMAC), `council/audit_envelope.py`, SHA256SUMS já usados no brandbook.
- Arquivos: novo `kernel/evidencia.py` (ou `tools/`), `tests/test_evidencia_pacote*`.
- Risco: baixo-médio (não capturar secrets no pacote — redaction do `safe_output`). Testes: pacote determinístico, hashes conferem, secrets nunca presentes.
- Pronto quando: `nomos missao evidencia <dir>` produz pacote verificável offline.
- Ordem: 2º (destrava 5 e 6).

**5. Agente Git Seguro**
- Objetivo: validar working tree, sugerir mensagem de commit, detectar ruído, montar handoff — **push sempre exige humano**.
- Base real: `tools/nomos_update_agent.py` (read-only/proposal-only, `--apply` fail-closed, `auto_push_enabled=false`) é o molde pronto; scripts de handoff MC24 mostram a necessidade real.
- Arquivos: novo `tools/nomos_git_agent.py`, `tests/test_git_agent*`, doc em `docs/governance/`.
- Risco: médio (nunca executar push/commit sem aprovação — herdar contrato fail-closed do update agent). Testes: push bloqueado por contrato; sugestão de commit não altera tree; JSON estável p/ CI.
- Pronto quando: `--check/--suggest` funcionam, `--push` não existe, aprovação humana obrigatória p/ `--commit`.
- Ordem: 3º.

**6. Brandbook + Site Sync Agent**
- Objetivo: manter README ↔ brandbook ↔ manual ↔ site ↔ changelog alinhados; detectar divergência e propor correção.
- Base real: `tools/nomos_update_agent.py` já checa existência/seções/links/secrets/git — faltam checks de marca: paleta congelada no CSS, tagline canônica, contagem de testes do README vs suíte, proibição `pip install nomos` (o incidente DESTA missão vira check permanente), versão pyproject vs docs.
- Arquivos: `tools/nomos_update_agent.py` (+checks), `tests/test_mc*_update_agent*`.
- Risco: baixo (read-only). Testes: cada check com caso positivo/negativo; gate de CI.
- Pronto quando: `--check` falha se qualquer contrato de marca/instalação quebrar.
- Ordem: 1º (menor esforço, maior prevenção imediata — teria pego os 3 achados desta missão).

**7. Camada Profissional de Segurança e Permissões (política formal)**
- Objetivo: consolidar em `docs/governance/SECURITY_POLICY.md` a política executável: escada A0–A6, comandos permitidos/bloqueados, dry-run default, fail-closed, aprovação humana, proteção de secrets — com testes lendo a política (docs = contrato).
- Base real: `kernel/policy.py` (A0–A6), `council/forbidden_flags.py` (contrato único CLI/chat, MC24), `prompt_guard.py`, `test_no_secret_leak_regression.py`, `test_prompt_injection.py` — a implementação existe; falta o documento-contrato único e o teste que o valida.
- Arquivos: `docs/governance/SECURITY_POLICY.md`, `tests/test_security_policy_contract.py`.
- Risco: baixo. Testes: cada afirmação da política mapeada a um teste real (estilo THREAT_MODEL, que já segue "cada garantia com o teste que a prova").
- Pronto quando: política publicada e CI falha se código divergir dela.
- Ordem: **1º-bis** (par com o item 6; ambos são a fundação anti-regressão).

**Ordem recomendada:** 7 → 6 → 4 → 5 (git agent) → 2 → 3 → 1
*(fundação de política/sync primeiro; painel por último, consumindo evidências/catálogo prontos).*

## 12. Próxima missão recomendada

Arquivo pronto para colar: `PROXIMA_MISSAO.md` (neste pacote). Resumo: **MC-APLICAR-HARDENING**
— aguardar a sessão concorrente commitar o WIP → aplicar patches 0001–0003 (+0004/site) →
adicionar suíte anti-regressão → atualizar CHANGELOG → rodar `pytest` + `ruff` → commit
único com aprovação humana → (opcional) iniciar implementação 6+7 do plano.

## 13. Encerramento (contratos da missão)

```
STATUS_FINAL=WARN_NOMOS_VALIDATED_WITH_PENDING_ITEMS
  (loop-100: WARN_PARTIAL_DELIVERY_WITH_EXPLICIT_GAPS — bloqueio real e documentado:
   operador determinou modo somente-diagnóstico por sessão concorrente ativa)
BRANCH=main
HEAD=d96e96a
TESTS=HEAD: 1108 pass + 6 falhas ambientais (todas passam no repo real: 108/109;
      única falha real = teste do WIP concorrente) · Snapshot pós-patch: 1126 pass,
      zero regressão · Suíte nova: 6/6
COVERAGE=não medida nesta sessão (pytest-cov disponível; ver §7)
GIT_DIRTY=4 M + 5 ?? (100% WIP da sessão concorrente; 0 alterações desta missão)
ARQUIVOS_ALTERADOS=nenhum no repo (modo diagnóstico)
DOCUMENTOS_CRIADOS=5 no pacote outputs (relatório, suíte anti-regressão, 4 patches, próxima missão)
RUÍDOS_TRATADOS=classificados 100% (remover 11 · arquivar 8 · revisar 4 · manter resto); nada apagado
ANTI_REGRESSAO=6 contratos novos validados (execução real OFF, brandbook hash, docs
      essenciais, .gitignore, anti pip-install-nomos, versão coerente)
SITE_STATUS=existe, em expansão ativa (WIP); testes do site passam no repo real;
      1 correção pendente (index.html:354, patch 0004)
BRANDBOOK_STATUS=congelado íntegro (4/4 hashes OK); expandido coerente após patch 0003
MANUAL_STATUS=existe e é bom; crítico após patch 0002 (colisão PyPI)
RISCOS_REMANESCENTES=5 (ver §10; nº1 = docs seguem com pip install nomos até aplicar)
PROXIMA_MISSAO_RECOMENDADA=MC-APLICAR-HARDENING (arquivo PROXIMA_MISSAO.md)
```

---

## 14. ADENDO — MC-APLICAR-HARDENING (2026-07-05, mesma data, sessão seguinte)

O operador autorizou consolidar o WIP ("WIP morreu — incluir site inteiro").
Resultado da aplicação:

- O teste "vermelho" da arbitragem era **ambiental** (pacote não instalado no
  sandbox de diagnóstico); com `pip install -e .`, 16/16 verdes — o WIP estava
  completo. Lock órfão `.git/index.lock` (16:58, 0 bytes) removido com evidência.
- Commit 1 `feat(cognition)`: arbitragem real + site expandido (9 arquivos, WIP).
- Commit 2 `fix(docs)`: patches 0001–0004 aplicados, INSTALL.md, pyproject URL,
  CHANGELOG, suíte anti-regressão em `tests/` (6/6).
- Gate final: **1139 passed** · ruff limpo · grep `pip install nomos` puro = 0.
- Push NÃO executado (aprovação humana).

STATUS_FINAL(desta aplicação)=PASS_100_DELIVERY_READY
