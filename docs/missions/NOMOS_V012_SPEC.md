# SPEC — Missão v0.12 "Distribuição real" (implementation-loop-100)

## Objetivo
Qualquer pessoa instala o NOMOS em minutos, por wheel de release ou instalador
de 1 clique, com CI garantindo qualidade em 3 SOs e atualização **manual e
consciente** via `nomos atualizar`.

## Escopo incluído
1. `.github/workflows/ci.yml` — pytest + ruff, matriz ubuntu/macos/windows ×
   Python 3.10–3.13; badge no README.
2. `.github/workflows/release.yml` — em tag `v*`: roda a suíte, constrói
   wheel+sdist, gera `SHA256SUMS`, cria a release com artefatos + instaladores.
3. Instaladores: manter/ajustar `install.sh`/`uninstall.sh`/`rollback.sh` e
   criar `install.ps1` + `uninstall.ps1` (Windows), com os mesmos princípios
   fail-closed (checksum, backup, purge só com confirmação digitada em TTY).
4. `nomos atualizar` — consulta a última release (api.github.com) SOMENTE
   após passar no gate A2 (cadeado ligado ⇒ negado com explicação; sem TTY ⇒
   negado); compara versões; mostra novidades e o comando manual de update;
   **nunca** baixa/instala sozinho.
5. Política anti-telemetria explícita em docs/PRIVACIDADE.md.
6. Versão 0.12.0; CHANGELOG; INSTALL.md/README atualizados; testes novos;
   relatório final.

## Fora de escopo
- Executar os workflows no GitHub (depende de `git push` do operador — os
  workflows são validados localmente: sintaxe YAML + os mesmos comandos que
  eles rodam são executados aqui).
- Publicação em PyPI/Homebrew/winget (v1.0).
- Auto-update (proibido por princípio, não só fora de escopo).

## Arquivos que poderei alterar
`.github/workflows/*` (novos), `installer/*`, `src/nomos/simple/atualizar.py`
(novo), `src/nomos/cli.py` (wiring do comando), `pyproject.toml`,
`src/nomos/__init__.py`, `README.md`, `CHANGELOG.md`, `docs/INSTALL.md`,
`docs/PRIVACIDADE.md`, `tests/test_atualizar.py` (novo), `docs/missions/*`.

## Arquivos proibidos (congelados)
Kernel: `src/nomos/kernel/*`, `src/nomos/runtime/*`, `src/nomos/ext/signing.py`,
`src/nomos/ext/skills.py`. Testes existentes não podem ser alterados
(somente adicionados).

## Critérios de aceite (verificáveis localmente)
| # | Critério | Verificação |
|---|---|---|
| 1 | Suíte 100% + ruff | `pytest -q`, `ruff check src tests` |
| 2 | Wheel constrói e instala limpo | `python -m build` → venv novo → `nomos --version` = 0.12.0 e `nomos doutor` rc=0 |
| 3 | SHA256SUMS gerado e confere | `sha256sum -c` no dist |
| 4 | YAML dos workflows válido | parse com PyYAML + comandos idênticos executados localmente |
| 5 | install.sh funciona de ponta a ponta | rodar num PREFIX temporário: instala, `nomos --version`, rollback e uninstall |
| 6 | `nomos atualizar`: cadeado ⇒ nega; sem TTY ⇒ nega; com aprovação+fetcher fake ⇒ compara e orienta; nunca executa instalação | testes + smoke |
| 7 | Nenhum segredo/telemetria | grep de regressão + testes existentes |
| 8 | Compat: todos os comandos v0.11 intactos | suíte antiga passa sem alteração |

## Testes/verificações planejados
`tests/test_atualizar.py` (comparação de versão, gates, fetcher injetado,
saída honesta), execução real de `installer/install.sh` em prefixo temporário,
build+install do wheel em venv limpo, validação YAML, suíte completa.

## Riscos conhecidos
- Ambiente de CI difere do sandbox local (mitigado: comandos idênticos, matriz
  conservadora, `PYTHONUTF8=1` no Windows).
- `api.github.com` indisponível em runtime do usuário ⇒ `nomos atualizar`
  responde honesto e não quebra (testado com fetcher que falha).

## Rollback
Histórico git (revert por commit); installer já tem `rollback.sh` com backup
de venv — mantido e testado.
