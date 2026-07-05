# SITE POLISH — Site NOMOS polido e completo

## 1. Status

```
STATUS_FINAL=PASS_SITE_POLISH_DELIVERY_READY
```

## 2. Objetivo

Polir e completar o site single-page do MC25, deixando-o profissional e autocontido,
local-first, sem deploy. Executado sob `implementation-loop-100` com evidência real.

## 3. HEAD

- HEAD inicial e final: `bbe2820` — nenhum commit criado.
- Branch: `main`.

## 4. O que foi entregue

| Item | Antes (MC25) | Agora |
|---|---|---|
| Favicon | ausente (referência quebrada) | `assets/favicon.svg` (marca NOMOS) + `<link rel=icon>` |
| Open Graph image | `og:image` apontava p/ PNG inexistente | `assets/og-image.png` 1200×630 real (Pillow) + fonte SVG |
| Twitter Card | ausente | `summary_large_image` + título/descrição/imagem |
| SEO head | básico | + canonical, theme-color, author, og:locale/site_name/width/height/alt |
| Acessibilidade | sem main/skip/aria | `<main id=conteudo>`, skip-link, `aria-label` na nav, `aria-labelledby` no hero, foco visível, `prefers-reduced-motion` |
| Página 404 | ausente | `404.html` branded |
| Preview/validação | só `python -m http.server` | `site/preview.py` (serve + `--check` read-only, stdlib) |
| Gerador de imagem | — | `assets/make_og_image.py` (reproduzível) |
| Docs | básico | `site/README.md` atualizado |

## 5. Arquivos criados/alterados

Criados: `site/assets/favicon.svg`, `site/assets/og-image.svg`, `site/assets/og-image.png`,
`site/assets/make_og_image.py`, `site/404.html`, `site/preview.py`,
`tests/test_site_polish.py`, `docs/missions/SITE_POLISH_SPEC.md`, este relatório.

Alterados: `site/index.html` (head SEO + acessibilidade, aditivo), `site/README.md`.

Não tocados: `.github/`, `pyproject.toml` (inexistente `setup.cfg`), `src/nomos/`.

## 6. Comandos executados (evidência real)

| Comando | Retorno | Resultado |
|---|---:|---|
| `python site/assets/make_og_image.py` | 0 | `og-image.png (1200x630)` |
| `python3 -c "PIL...size"` | 0 | `(1200, 630) RGB` |
| `python site/preview.py --check` | 0 | OK — assets, links, a11y |
| `curl / ` (preview.py serve :8077) | — | HTTP 200, 19308 bytes, hero presente |
| `curl /assets/og-image.png` | — | HTTP 200, 43925 bytes, image/png |
| `curl /assets/favicon.svg` | — | HTTP 200, image/svg+xml |
| `curl /404.html` | — | HTTP 200 |
| `pytest tests/test_site_polish.py -v` | 0 | 12 passed |
| `python tools/nomos_update_agent.py --check` | 0 | links:landing resolvem, CONSISTENTE |
| `pytest tests/test_mc25_deliverables.py tests/test_site_polish.py -q` | 0 | 57 passed |
| `ruff check .` | 0 | All checks passed! |
| `pytest -q` (bare) | 0 | 1111 passed |
| `git diff --stat .github/ pyproject.toml` | 0 | vazio (intactos) |

## 7. Testes reais (tests/test_site_polish.py — 12)

Assets existem e não-vazios; favicon SVG válido; og-image PNG exatamente 1200×630 (lido do
header IHDR, sem deps); index/404 parseiam; estrutura (`main`/`header`/`footer`); SEO
(og:image/width/height, twitter:card, canonical, theme-color); og:image aponta p/ asset
existente; acessibilidade (1 `<h1>`, `lang=pt-BR`, `<main>`, skip-link, imgs com alt);
links locais resolvem; sem segredos; `preview.py --check` sai 0 e **não escreve** (mtimes
preservados).

## 8. Evidência de segurança

```
LOCAL_FIRST=YES              (preview.py serve em 127.0.0.1; --check sem rede)
NO_DEPLOY=YES                (nenhuma publicação; apenas preview/validação local)
NO_PUSH=YES / NO_TAG=YES / NO_RELEASE=YES / NO_PYPI=YES
NO_SECRET_LEAK=YES           (test_site_sem_segredos + scan)
NO_WRITE_ON_CHECK=YES        (preview.py --check preserva mtimes)
FORBIDDEN_FILES_INTACT=YES   (.github/, pyproject.toml sem diff; setup.cfg inexistente)
HUMAN_APPROVAL_REQUIRED=YES  (commit/push/publicação são ação humana)
```

## 9. Critério de 100%

```
SPEC_DECLARED=TRUE
SCOPE_RESPECTED=TRUE
IMPLEMENTATION_DONE=TRUE
TESTS_EXECUTED=TRUE
TESTS_PASSING=TRUE          (site 12; MC25 45; suíte 1111)
VALIDATION_EXECUTED=TRUE    (preview --check + smoke HTTP 200)
REGRESSION_CHECKED=TRUE
KNOWN_GAPS=DOCUMENTED_NON_BLOCKING
EVIDENCE_RECORDED=TRUE
STATUS_FINAL=PASS_SITE_POLISH_DELIVERY_READY
```

## 10. Limitações honestas (KNOWN_GAPS)

- og:image é PNG estático; se a tagline/marca mudar, rode `make_og_image.py` (requer Pillow, dep dev).
- O site continua single-page (por decisão de escopo "polir e completar"); expansão
  multi-página fica para incremento futuro.
- `canonical`/`og:url` usam o domínio `nomos.se7enpay.com` como placeholder; ajustar ao
  domínio real na publicação.
- Nenhum deploy/config de CI foi criado (fora de escopo); publicação é ação humana.
- Assets do site seguem untracked; commit é decisão humana.

## 11. Próximo passo recomendado

**SITE-2 — Expansão multi-página + preparação de publicação (sem publicar):**
páginas dedicadas (docs index, instalação, segurança) com navegação, `sitemap.xml`,
`robots.txt` e config de GitHub Pages — mantendo `preview.py --check` como gate local e
sem nenhum deploy/push automático.
