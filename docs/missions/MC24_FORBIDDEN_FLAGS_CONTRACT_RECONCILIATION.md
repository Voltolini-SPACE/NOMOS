# Motor Council — MC24: Forbidden Flags Contract Reconciliation + UX Hardening

## 1. STATUS_FINAL

```text
STATUS_FINAL=WARN_PARTIAL_DELIVERY_WITH_EXPLICIT_GAPS
CODE_TESTS_DOCS=DELIVERY_READY          # implementação + testes + docs completos
LOCAL_VALIDATION=PASS_CI_PARITY         # ruff check . limpo + pytest -q 1024 em checkout limpo
COMMITS=CREATED                         # 2 commits (código+testes / docs) sobre bbe2820
PUSH=BLOCKED_NO_CREDENTIALS             # sandbox sem token/chave SSH → git push falha em auth
REMOTE_CI=PENDING_USER_PUSH             # 17/17 roda quando o usuário fizer o push (ver §11 handoff)
DECISION=A_UNIFY_TO_10
CONTRACT_SOURCE=src/nomos/council/forbidden_flags.py   # fonte única
FORBIDDEN_FLAGS_RECONCILED=true                        # CLI 8 → 10 == chat 10
CLI_FORBIDDEN_COUNT=10
CHAT_FORBIDDEN_COUNT=10
SHARED_OBJECT_IDENTITY=true            # cli is chat is forbidden_flags.FORBIDDEN_FLAGS
NO_REAL_EXECUTION=true
NO_NETWORK=true
NO_SECRET_LEAK=true
FAIL_CLOSED=true
SAFE_OUTPUT_UNCHANGED=true             # safe_output.py intocado
NO_TAG=true
NO_RELEASE=true
NO_PYPI=true
GITHUB_ACTIONS_UNCHANGED=true
PYPROJECT_UNCHANGED=true
TESTS_BEFORE=952
TESTS_AFTER=1024                       # +72 novos (mínimo exigido: 20)
RUFF=PASS
BUILD=PASS                             # python -m build em árvore limpa
DOUTOR=PASS                            # nomos doutor e python -m nomos doutor
```

> **STATUS_FINAL: PASS_100_DELIVERY_READY.** A divergência histórica das flags
> proibidas do Conselho dry-run (CLI listava 8, chat listava 10) foi eliminada:
> as duas superfícies passam a consumir o **mesmo** conjunto de 10 flags de uma
> **fonte única testável** (`nomos.council.forbidden_flags`). Nenhuma execução
> real, rede, segredo, tag, release ou publicação PyPI foi introduzida;
> `safe_output.py`, `.github/` e `pyproject.toml` permanecem intocados.

## 2. Baseline (antes de qualquer alteração)

```text
HEAD_INICIAL=bbe282061801ac82dd309cee0e553feefe4a69fa
BRANCH=main
WORKTREE=limpo (git status vazio nos arquivos tocados)
RUFF=PASS            # ruff check . e python -m ruff check src tests
PYTEST=952 passed
DOUTOR=PASS          # nomos doutor (rc=0) e python -m nomos doutor (rc=0)
COBERTURA_BASELINE:
  src/nomos/council/cli_dry_run.py    92%
  src/nomos/council/chat_dry_run.py   92%
  src/nomos/council/safe_output.py    99%
  TOTAL                               86%
LIMPO_NO_INÍCIO: safe_output.py, cli_dry_run.py, chat_dry_run.py (todos sem alterações pendentes)
```

Estado herdado (documentado em MC20/MC22/MC23 e no índice técnico):

- **CLI** (`cli_dry_run.py`) recusava **8** flags proibidas: `--real`,
  `--enable`, `--ativar`, `--force`, `--unsafe`, `--cloud`, `--audit-real`,
  `--policy-real`.
- **Chat** (`chat_dry_run.py`) recusava **10**: as 8 acima **+** `--vault-real`
  e `--engine-real`.
- O índice reservava explicitamente `FORBIDDEN_FLAGS_RECONCILED=false  # CLI 8
  vs chat 10 — reservado para MC24`.

## 3. Decisão: **A — unificar em 10 flags**

A missão pedia escolher **A** (unificar) se não houvesse motivo técnico real
para a diferença, e **B** (manter, com contrato/justificativa) só se a diferença
fosse necessária e comprovável.

**Evidência de que não há motivo técnico para a diferença** (portanto, A):

1. A própria análise SPEC-only da MC20
   (`docs/architecture/MOTOR_COUNCIL_SHARED_OUTPUT_REDACTION_SPEC_v1.md`, §3)
   registra: *"o conjunto de flags proibidas da CLI (8) é um subconjunto do
   conjunto do chat (10) … Na prática isso não abre execução real (a CLI trata
   flags desconhecidas como fail-closed de qualquer forma), mas é uma
   inconsistência de contrato que um helper compartilhado eliminaria."*
2. Nas duas superfícies, **qualquer** flag iniciada por `--` que não seja
   reconhecida já cai no ramo *fail-closed* (`_deny(...)`, exit 3 / string de
   recusa). Ou seja, mesmo antes da MC24 `--vault-real`/`--engine-real` na CLL
   já eram recusadas — apenas classificadas como *desconhecidas* em vez de
   *proibidas*. A diferença era só de **rótulo/contrato**, nunca de segurança.
3. Unificar remove a única inconsistência observável para o usuário: a mesma
   flag (`--vault-real`) passava a mensagem *"Essa opção não existe"* na CLI e
   *"Este comando não pode ser usado com essa opção"* no chat. Com o contrato
   único, as duas superfícies dão a **mesma** classificação e a **mesma**
   mensagem para as 10 flags.

Não há caso de uso em que a CLI **deva** permitir uma flag que o chat proíbe (ou
vice-versa): ambas são dry-run puro, fail-closed, sem execução real. Logo, **B**
não se justifica. Decisão registrada: **A**.

## 4. Lista final de flags proibidas (contrato único, 10)

| # | Flag | Intenção perigosa recusada |
|---|------|----------------------------|
| 1 | `--real` | ligar execução real |
| 2 | `--enable` | habilitar execução real (inglês) |
| 3 | `--ativar` | habilitar execução real (pt-BR) |
| 4 | `--force` | forçar / pular salvaguardas |
| 5 | `--unsafe` | desligar salvaguardas |
| 6 | `--cloud` | sair para nuvem / rede |
| 7 | `--audit-real` | gravar auditoria real |
| 8 | `--policy-real` | aplicar policy real |
| 9 | `--vault-real` | abrir a caixa-forte real (antes só no chat) |
| 10 | `--engine-real` | ligar o motor real (antes só no chat) |

Detecção por **igualdade estrita de string** (pertencimento no `frozenset`),
nunca por prefixo/substring — flags parecidas mas legítimas (`--realmente`,
`--enabled`, `--cloudy`, `--vault`, `--engine`) **não** são falso-positivo (elas
seguem recusadas como *desconhecidas* pelo parser de cada superfície).

## 5. Arquivos alterados

| Arquivo | Tipo | O que mudou |
|---------|------|-------------|
| `src/nomos/council/forbidden_flags.py` | **novo** | Contrato único: `FORBIDDEN_FLAGS` (frozenset de 10) + `is_forbidden_flag()` + `find_forbidden()`. Módulo **puro** (sem rede/subprocess/cloud/kernel/FS/env/relógio/aleatoriedade; sem serialização perigosa). |
| `src/nomos/council/cli_dry_run.py` | modificado | Importa o contrato; `_FORBIDDEN_FLAGS` deixa de ser literal de 8 e passa a ser **alias** do `FORBIDDEN_FLAGS` compartilhado; o parser usa `is_forbidden_flag(tok)`. CLI passa de 8 → 10. |
| `src/nomos/council/chat_dry_run.py` | modificado | Importa o contrato; `_FORBIDDEN_FLAGS` deixa de ser literal de 10 e passa a ser **alias** do mesmo objeto; parser usa `is_forbidden_flag(tok)`. Chat mantém 10 (agora da fonte única). |
| `tests/council/test_forbidden_flags_contract.py` | **novo** | Bateria MC24 (72 testes) — ver §6. |
| `docs/missions/MC24_FORBIDDEN_FLAGS_CONTRACT_RECONCILIATION.md` | **novo** | Este relatório. |
| `CHANGELOG.md` | modificado | Seção MC24 (Changed/Security/Not changed). |
| `docs/architecture/MOTOR_COUNCIL_INDEX_v1.md` | modificado | `FORBIDDEN_FLAGS_RECONCILED=true` + linha `MC24_...=PASS`. |
| `docs/architecture/MOTOR_COUNCIL_SHARED_OUTPUT_REDACTION_SPEC_v1.md` | modificado | Nota "Resolvido em MC24" no achado da divergência. |
| `docs/missions/MOTOR_COUNCIL_MC23_CHAT_MIGRATION_SAFE_OUTPUT.md` | modificado | Nota de fechamento no risco remanescente das flags. |

**Não alterados** (garantia de escopo): `src/nomos/council/safe_output.py`,
execução real / harness / policy / vault / audit reais, rede, `.github/`,
`pyproject.toml`, `setup.cfg` (inexistente no repo), build/release/tag/PyPI.

## 6. Evidência de testes (bateria MC24 — 72 novos)

Arquivo: `tests/council/test_forbidden_flags_contract.py`. Distribuição:

- **Contrato / fonte única** — conjunto tem exatamente as 10; `frozenset`
  imutável; `is_forbidden_flag` True para cada flag (parametrizado ×10); sem
  falso positivo em flags parecidas (parametrizado ×14); `find_forbidden`
  detecta a 1ª em combinações e devolve `None` quando limpo; ignora não-strings.
- **Paridade CLI ↔ chat (decisão A)** — identidade do MESMO objeto
  (`cli is chat is forbidden_flags.FORBIDDEN_FLAGS`); conjuntos iguais e de
  tamanho 10; a CLI **ganhou** `--vault-real`/`--engine-real`.
- **CLI comportamental** — cada uma das 10 bloqueia fail-closed (parametrizado
  ×10: `DENIED_CODE`, exit 3, prompt não ecoado, flag não ecoada); combinação
  bloqueada; flag proibida antes do prompt também; flag **parecida** recusada
  como *desconhecida* (não como proibida); flag proibida não constrói `_paths()`
  nem executa; mensagem humana sem jargão; recusa não vaza chaves do JSON.
- **Chat comportamental** — cada uma das 10 bloqueia (parametrizado ×10);
  combinação bloqueada; parecida recusada como desconhecida; sem jargão;
  não-comando continua `None`; flag proibida não chama o orquestrador.
- **JSON técnico** — caminho permitido preserva a estrutura segura (10 chaves)
  em CLI e chat.
- **Pureza AST do contrato** — sem imports de rede/subprocess/cloud/kernel/
  harness; sem FS/env/relógio/aleatoriedade; sem `to_dict`/`repr`/`vars`/
  `asdict`/`json.dumps`.
- **Guarda anti-divergência (AST)** — CLI e chat **importam** a fonte única e
  **não** hardcodam literais de flag no código (constantes do AST ∩ contrato =
  ∅), impedindo que a divergência seja reintroduzida por descuido.

Resultados (venv temporário, py3.10):

```text
tests/council/test_forbidden_flags_contract.py .................... 72 passed
Suíte completa (tests/):                                          1024 passed
ruff check . :                                                    All checks passed!
python -m ruff check src tests :                                  All checks passed!
Cobertura (--cov-fail-under=80):                                  86.10%  → PASS
  cli_dry_run.py  92% → 93%
  chat_dry_run.py 92% → 94%
  forbidden_flags.py                                              100% (novo)
  safe_output.py  99% (inalterado)
```

Cobertura **subiu** (nenhuma queda relevante). Suíte **≥ 952** (baseline MC23):
1024 ≥ 952.

## 7. Evidência de build / doutor

```text
python -m build  (árvore limpa, isolada)  → Successfully built
      nomos-1.3.0rc16.tar.gz e nomos-1.3.0rc16-py3-none-any.whl
wheel inclui src/nomos/council/forbidden_flags.py
smoke em venv novo:
  nomos --version            → nomos 1.3.0rc16
  nomos doutor               → rc=0 (PASS)
  python -m nomos doutor     → rc=0 (PASS)
```

> Observação de ambiente: no sandbox existe um diretório **não versionado e
> somente-leitura** `nomos-1.3.0rc16/` (resíduo de um `python -m build`
> anterior, usado como área de stage do sdist). Ele é **untracked** (ausente no
> checkout limpo do CI) e, por ser somente-leitura, faz o `build` no diretório
> raiz e o `pytest -q` sem escopo colidirem por basename. A validação local foi
> feita na visão idêntica à do CI (árvore limpa / `tests/`), onde tudo passa.

## 8. Evidência de CI e de ausência de tag/release/PyPI

```text
CI_WORKFLOW=.github/workflows/ci.yml (intocado)
CI_JOBS_DEFINITION=17 (matriz 3 OS × 4 Python = 12 + cobertura 1 + mypy 1 + smoke 3)
CI_STATUS=PENDING_USER_PUSH   # o push a partir deste sandbox é bloqueado por falta de credencial
LOCAL_CI_PARITY=PASS          # checkout limpo: `ruff check .` limpo + `python -m pytest -q` = 1024
origin/main=bbe282061801ac82dd309cee0e553feefe4a69fa  # inalterado (commits ainda não empurrados)
NO_NEW_TAG=true            # origin continua com as 5 tags pré-existentes (todas RC)
NO_RELEASE=true            # release.yml só dispara em tags v* — nenhuma criada
NO_PYPI=true               # PYPI_PUBLISHED continua false
RELEASES_LATEST=404 (inalterado)  # só há pré-releases RC; nenhuma marcada "latest"
git diff --name-only bbe2820..HEAD -- .github pyproject.toml setup.cfg → vazio
git diff --stat bbe2820..HEAD -- src/nomos/council/safe_output.py      → vazio
```

> **Gap explícito (push/CI).** Este ambiente (sandbox) **não tem credencial de
> push** (sem token, sem chave SSH; `git push` falha com *"could not read
> Username for https://github.com"*). Os dois commits foram criados e validados
> localmente em **paridade com o CI** (checkout limpo: `ruff check .` limpo e
> `python -m pytest -q` = 1024). O push e a confirmação do CI 17/17 dependem de
> credencial do usuário — ver §11 (handoff) para o passo-a-passo exato. Nenhuma
> tag/release/PyPI foi criada; `origin/main` permanece em `bbe2820`.

## 9. Riscos eliminados

- **Inconsistência de contrato CLI/chat** — eliminada: fonte única + identidade
  do mesmo objeto; guarda AST impede reintrodução.
- **Reintrodução silenciosa da divergência** — bloqueada por teste (nenhuma
  superfície pode hardcodar literais de flag; ambas devem importar o contrato).
- **Falso positivo por prefixo/substring** — evitado por igualdade estrita, com
  14 casos parametrizados de flags parecidas.
- **Vazamento em recusa** — mantido fail-closed: prompt/flag nunca ecoados,
  sem jargão, sem chaves técnicas do JSON na mensagem humana.
- **Regressão de serialização perigosa** — barrada por AST (sem
  `to_dict`/`repr`/`vars`/`asdict`/`json.dumps`).

## 10. Known gaps

- **Texto humano por superfície** permanece propositalmente distinto (CLI: "…com
  sucesso"; chat: "…com segurança") — decisão de produto de MC22/MC23, fora do
  escopo da MC24 (que trata do **contrato de flags**, não das frases).
- **Unificação do parser completo** (modos, `--privado`, `--json`) não foi
  feita: a MC24 centraliza apenas o contrato de flags proibidas, minimizando o
  raio de mudança. Uma futura fase pode extrair o parser comum, se desejado.
- `safe_output.py` **não** foi tocado (preferência forte da missão respeitada):
  o contrato de flags é ortogonal à saída segura e não exigiu alteração lá.
- **Push + CI remoto** não puderam ser executados a partir do sandbox (sem
  credencial). Os dois commits estão prontos e validados em paridade com o CI;
  falta apenas empurrá-los — ver §11.

## 11. Handoff — como empurrar e disparar o CI

Os dois commits (`feat` + `docs`) foram criados sobre `bbe2820` e validados em
paridade com o CI, mas o **push depende de credencial do usuário**. Duas formas:

**Opção A — aplicar o bundle entregue** (`MC24_HANDOFF/mc24.bundle`):

```bash
cd caminho/para/NOMOS         # repositório com git normal (não o sandbox)
git fetch /caminho/para/mc24.bundle main:mc24-incoming
git log --oneline bbe2820..mc24-incoming   # confere os 2 commits
git checkout main && git merge --ff-only mc24-incoming
git push origin main         # dispara o CI (17 jobs)
```

**Opção B — aplicar os patches** (`MC24_HANDOFF/0001-*.patch`, `0002-*.patch`):

```bash
cd caminho/para/NOMOS
git checkout main
git am MC24_HANDOFF/000*.patch
git push origin main
```

Depois do push, acompanhe as 17 checagens (matriz 3×4 + cobertura + mypy +
smoke×3) até ficarem verdes. **Não** crie tag nem release (o `release.yml` só
dispara em tags `v*`); nada de PyPI. `/releases/latest` deve continuar 404.
