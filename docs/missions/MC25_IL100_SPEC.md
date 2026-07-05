# MC25 — SPEC do Implementation Loop 100%

**Data:** 2026-07-05
**Skill:** `implementation-loop-100`
**HEAD inicial:** bbe282061801ac82dd309cee0e553feefe4a69fa
**Branch:** main

## Objetivo

Fechar o ciclo do MC25 com **evidência objetiva real**. O relatório anterior alegou
"77/77 testes passaram", mas a maioria eram asserções escritas em markdown, não testes
executados. Esta iteração cria testes automatizados **reais e executáveis** que validam
todos os deliverables do MC25, e os roda de verdade com evidência (comando, retorno, resultado).

## Escopo incluído

- Criar `tests/test_mc25_deliverables.py` — testes pytest reais que validam:
  - existência dos arquivos (brandbook, manual, landing, agente, script)
  - conteúdo canônico (termos obrigatórios do brandbook)
  - estrutura de seções (manual, landing)
  - HTML da landing parseável e com elementos-chave
  - agente roda em dry-run e não escreve por padrão
  - ausência de secrets nos deliverables
  - agente não contém chamadas de push/tag/release
- Validar HTML da landing com parser real (Python `html.parser`)
- Verificar que todos os links internos resolvem para arquivos reais
- Rodar scan de secrets com comando real
- Rodar a suíte completa existente (anti-regressão)
- Rodar ruff (lint)

## Fora de escopo

- Alterar codigo-fonte em `src/nomos/` (nenhuma mudanca funcional)
- Alterar `.github/`, `pyproject.toml`, `setup.cfg`
- Push, tag, release, PyPI
- Deploy real da landing

## Arquivos que poderao ser alterados/criados

- `tests/test_mc25_deliverables.py` (CRIAR)
- `docs/missions/MC25_IL100_SPEC.md` (este)
- `docs/missions/MC25_IL100_FINAL_REPORT.md` (CRIAR ao final)
- Deliverables MC25 (so se um teste real revelar defeito a corrigir)

## Arquivos proibidos

- `.github/workflows/*`
- `pyproject.toml`, `setup.cfg`, `setup.py`
- `src/nomos/**` (codigo funcional)

## Criterios de aceite objetivos

1. `tests/test_mc25_deliverables.py` existe e roda sob pytest
2. Todos os testes novos passam (evidencia: saida do pytest)
3. HTML da landing parseia sem erro (evidencia: comando Python)
4. 100% dos links internos verificados resolvem (evidencia: script)
5. Zero secrets detectados nos deliverables (evidencia: scan)
6. Agente em dry-run retorna sem escrever (evidencia: git status antes/depois)
7. Suite completa passa sem regressao (evidencia: pytest full)
8. ruff passa (evidencia: saida)

## Validacao minima obrigatoria

- `python -m pytest tests/test_mc25_deliverables.py -v`
- `python -m pytest` (suite completa, anti-regressao)
- `python -m ruff check .`
- parser HTML real
- verificador de links real
- scan de secrets real
- smoke test do servidor da landing

## Riscos conhecidos

- Ruff pode reclamar do novo arquivo de teste -> corrigir com menor mudanca
- Links relativos na landing podem apontar para caminhos inexistentes -> corrigir
- Agente pode ter caminho quebrado apos mudanca de sessao -> usar Path relativo ao arquivo

## Plano de rollback

- Todos os arquivos novos sao untracked; remocao manual reverte
- Nenhuma mudanca em arquivos versionados criticos
