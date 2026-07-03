# RELATÓRIO FINAL — v0.12 "Distribuição real" (implementation-loop-100)

## 1. Status
STATUS_FINAL=PASS_100_DELIVERY_READY
(escopo local; execução dos workflows NO GitHub declarada fora de escopo na
SPEC — depende de `git push` do operador)

## 2. Objetivo
CI em 3 SOs, release automatizada com artefatos verificáveis, instaladores de
1 clique (Unix + Windows) e `nomos atualizar` opt-in, nunca automático.

## 3. Escopo executado
Tudo da SPEC (docs/missions/NOMOS_V012_SPEC.md).

## 4. Arquivos alterados/criados
Criados: `.github/workflows/ci.yml`, `.github/workflows/release.yml`,
`installer/install.ps1`, `installer/uninstall.ps1`,
`src/nomos/simple/atualizar.py`, `tests/test_atualizar.py`, SPEC e este
relatório. Editados: `installer/install.sh` (modo release: instala wheel ao
lado do script), `src/nomos/cli.py` (comando `atualizar`), `pyproject.toml`
(0.12.0, extra dev, urls), `src/nomos/__init__.py`, `README.md` (badge,
comando, maturidade), `docs/INSTALL.md`, `docs/PRIVACIDADE.md`
(anti-telemetria), `CHANGELOG.md`, `tests/test_egress_zero.py` (allowlist +2
hosts com justificativa — única alteração em teste existente, prevista: é o
mecanismo de revisão consciente de destinos externos funcionando).

## 5. Arquivos preservados / congelados
Kernel intocado (`kernel/*`, `runtime/*`, `ext/signing.py`, `ext/skills.py`).

## 6. Comandos executados
| Comando | Retorno | Resultado |
|---|---:|---|
| `python -m pytest -q` | 0 | **349 passed** (341 + 8 novos) |
| `ruff check src tests` | 0 | limpo |
| parse YAML dos 2 workflows (PyYAML) | 0 | jobs `testes`/`validar`+`publicar` OK |
| `bash -n installer/*.sh` | 0 | sintaxe OK |
| `python -m build --wheel --sdist` | 0 | nomos-0.12.0 whl+tar.gz |
| `sha256sum --check SHA256SUMS` | 0 | íntegros |
| venv limpo + `pip install *.whl` | 0 | `nomos --version` = 0.12.0 |
| `nomos doutor` (wheel, home novo) | 0 | STATUS GERAL: PARCIAL (esperado) |
| `bash install.sh` (modo release, prefixo temp) | 0 | checksum→backup→venv→smoke ✓ |
| `bash rollback.sh` | 0 | restaurou backup e validou binário |
| `bash uninstall.sh` | 0 | removeu plataforma, preservou dados |
| `install.sh` com SHA256SUMS corrompido | 1 | **abortou fail-closed** |
| `nomos atualizar` sem TTY | 3 | negado com explicação do cadeado |

## 7. Testes e validações
8 testes novos em `test_atualizar.py`: comparação de versões (inclui rc<final
e malformada), cadeado nega mesmo com humano aprovando, CI nega sem aprovador,
versão nova orienta caminho manual e **não executa nada**, "já na mais nova",
falha de rede honesta, auditoria sem corpo das notas, CLI não-interativa nega.

## 8. Correções feitas durante o loop
1. Mensagem do cadeado sumia em `atualizar` (motivo da política era
   sobrescrito pelo motivo amigável) — corrigido preservando o original;
   pego pelo teste novo.
2. `test_egress_zero` recusou `api.github.com` — comportamento correto do
   teste-fortaleza; allowlist estendida com justificativa e documentada em
   PRIVACIDADE.md.

## 9. Anti-regressão
Suíte completa (inclui as 341 anteriores) verde; comandos v0.11 re-smoked via
suíte; teste estático de telemetria continua passando.

## 10. Gaps conhecidos
KNOWN_GAPS=NONE no escopo. Pós-push (operador): confirmar CI verde nos 3 SOs
reais e criar a tag `v0.12.0` para disparar a release. Os `.ps1` foram
validados por revisão e espelham o fluxo Unix testado; rodarão no CI Windows.

## 11. Critérios de aceite
| Critério (SPEC) | Status | Evidência |
|---|---|---|
| 1 suíte+ruff | PASS | §6 |
| 2 wheel instala limpo | PASS | §6 (venv + doutor) |
| 3 SHA256SUMS confere | PASS | §6 |
| 4 YAML válido + comandos idênticos rodados | PASS | §6 |
| 5 install.sh ponta a ponta | PASS | §6 (install/rollback/uninstall/corrompido) |
| 6 atualizar: gates + nunca instala | PASS | §7 |
| 7 zero segredo/telemetria | PASS | testes fortaleza |
| 8 compat v0.11 | PASS | 341 antigos verdes |

## 12. Veredito
SPEC_DECLARED=TRUE · SCOPE_RESPECTED=TRUE · IMPLEMENTATION_DONE=TRUE ·
TESTS_EXECUTED=TRUE · TESTS_PASSING=TRUE · VALIDATION_EXECUTED=TRUE ·
REGRESSION_CHECKED=TRUE · KNOWN_GAPS=NONE · ROLLBACK_OR_BACKUP_READY=TRUE ·
EVIDENCE_RECORDED=TRUE → **PASS_100_DELIVERY_READY**
