# SITE POLISH — SPEC (implementation-loop-100)

**Data:** 2026-07-05 · **HEAD:** bbe2820 · **Branch:** main

## Objetivo
Polir e completar o site single-page (`site/index.html`) do MC25, deixando-o
profissional e autocontido, local-first, sem deploy.

## Escopo incluído
- Criar `site/assets/favicon.svg` (hoje referenciado implicitamente, inexistente).
- Gerar `site/assets/og-image.png` (1200x630) — hoje referenciado no og:image, inexistente.
  Fonte SVG `site/assets/og-image.svg`.
- Polir `site/index.html`: favicon link, theme-color, canonical, Twitter Card,
  skip-link, `<main>`, `aria-*`, foco visível — preservando conteúdo/estilo.
- Criar `site/404.html` simples e branded.
- Criar `site/preview.py` (stdlib): serve local + `--check` valida assets/links (sem rede).
- Atualizar `site/README.md`.
- Criar `tests/test_site_polish.py` (testes reais).

## Fora de escopo / proibido
- Deploy real, push, tag, release, PyPI.
- Alterar `.github/`, `pyproject.toml`, `setup.cfg`, `src/nomos/`.
- Dependências pesadas (usar só stdlib + Pillow já instalado para o PNG).
- Rede externa em runtime de teste/preview.

## Critérios de aceite (verificáveis)
1. `site/assets/favicon.svg` e `site/assets/og-image.png` existem e não-vazios.
2. `index.html` referencia favicon e og-image; HTML parseia sem erro.
3. Todos os assets/links internos do index resolvem para arquivos reais.
4. Acessibilidade básica: 1 `<h1>`, `<main>`, skip-link, `lang`, nav com aria-label.
5. `site/preview.py --check` sai 0 e valida assets sem rede.
6. `tests/test_site_polish.py` passa.
7. Smoke test: servidor local responde HTTP 200 com hero.
8. `ruff check .` e `pytest -q` passam (anti-regressão).
9. `.github/`, `pyproject.toml`, `setup.cfg` sem diff.

## Validação
pytest, ruff, parser HTML stdlib, verificador de links stdlib, smoke HTTP, Pillow p/ PNG.

## Riscos
- Fonte para PNG: usar TrueType do sistema ou `ImageFont.load_default(size=)`.
- og:image absoluto (domínio) mas arquivo existe local p/ preview relativo.

## Rollback
Todos os arquivos novos untracked; index.html tem backup lógico via git (untracked, mas
alterações são aditivas e reversíveis).
