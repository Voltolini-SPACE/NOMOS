# REBRAND — Alinhamento ao Brandbook v1.0 (congelado)

## 1. Status

```
STATUS_FINAL=PASS_SITE_REBRAND_FROZEN_ALIGNED
```

## 2. Reconhecimento do erro

No MC25 eu **inventei** uma identidade visual (azul `#1B73E8`, verde `#34A853`, fundo
branco, tipografia sans-serif) para o brandbook e o site, **sem consultar o Brandbook v1.0
congelado do NOMOS**, que já existia em `Desktop/MARCA_NOMOS/` e define uma identidade
**terminal escuro + verde-neon `#5AF78E` + monospace**. O usuário apontou a falha
corretamente. Esta correção alinha tudo ao congelado.

## 3. Fonte de verdade (congelada, verificada por SHA256)

Brandbook v1.0 — `MARCA_NOMOS/`:
- Logo ASCII shadow blocks, verde-neon `#5AF78E` sobre preto terminal `#0A0F0D`.
- Paleta: `#0A0F0D` bg · `#111814` superfície · `#5AF78E` neon · `#E8FFE8` texto ·
  `#FF5FA2` rosa · `#56E1E9` ciano · `#F2C14E` amarelo · `#FF5C57` vermelho.
- Tipografia: monospace (JetBrains Mono; fallback IBM Plex Mono, SF Mono, Menlo, Consolas).
- Tagline: "Seu agente. Sua máquina. Suas regras." · assinatura "local por lei".
- Léxico: caixa-forte, senha-mestra, modo só-local/cadeado, motor/cérebro, plugar a nuvem.

## 4. O que foi corrigido

| Item | Antes (inventado) | Agora (congelado) |
|---|---|---|
| Fundo do site | branco `#fff` | preto terminal `#0A0F0D` |
| Cor da marca | azul `#1B73E8` | verde-neon `#5AF78E` |
| Tipografia | sans-serif (-apple-system) | monospace (stack local, sem CDN) |
| Hero | texto simples | logo ASCII shadow em verde-neon + cursor `▋` |
| Componentes | cards genéricos | blocos de terminal, do/dont, glow neon |
| favicon | "N" azul geométrico | N em blocos verde-neon sobre fundo escuro |
| og-image | azul/branco sans | terminal escuro, wordmark neon, monospace |
| 404 | branco/azul | terminal escuro branded |
| Brandbook expandido | paleta/fonte inventadas | corrigido + aponta o congelado como fonte de verdade |

## 5. Arquivos criados/alterados

Criados: `docs/brand/frozen/` (BRANDBOOK_NOMOS.md, brandbook_nomos.html, logo/símbolo
ASCII, SHA256SUMS — cópia verbatim do congelado); `docs/missions/SITE_REBRAND_FROZEN_BRANDBOOK.md`.

Alterados: `site/index.html` (reconstruído na marca congelada), `site/404.html`,
`site/assets/favicon.svg`, `site/assets/og-image.svg`, `site/assets/make_og_image.py`,
`site/assets/og-image.png` (regenerado), `docs/brand/NOMOS_BRANDBOOK.md` (paleta/fonte
corrigidas + ponteiro canônico), `tests/test_site_polish.py` (testes de fidelidade +
integridade do congelado), `tests/test_mc25_deliverables.py` (2 asserções de landing
atualizadas para âncoras estáveis).

Não tocados: `.github/`, `pyproject.toml` (sem `setup.cfg`), `src/nomos/`.

## 6. Comandos executados (evidência real)

| Comando | Retorno | Resultado |
|---|---:|---|
| `sha256sum -c SHA256SUMS` (congelado no repo) | 0 | 4/4 OK |
| `python site/assets/make_og_image.py` | 0 | og-image.png 1200×630 (dark/neon) |
| `python site/preview.py --check` | 0 | site consistente |
| `python tools/nomos_update_agent.py --check` | 0 | links da landing resolvem |
| `ruff check .` | 0 | All checks passed! |
| smoke `curl /` | — | HTTP 200; logo ASCII e `#5AF78E` presentes |
| smoke `curl /assets/og-image.png` | — | HTTP 200, image/png |
| `pytest tests/test_site_polish.py tests/test_mc25_deliverables.py -q` | 0 | 60 passed |
| `pytest -q` (bare) | 0 | 1114 passed |
| `git diff --stat .github/ pyproject.toml` | 0 | vazio (intactos) |

## 7. Novos testes de proteção (anti-recaída)

`tests/test_site_polish.py` agora trava a identidade:
- `test_index_fiel_ao_brandbook_congelado`: exige `#5AF78E`, `#0A0F0D`, `monospace`, logo
  `█`, tagline e "local por lei"; **proíbe o retorno de `#1B73E8`**.
- `test_theme_color_e_terminal`: `theme-color` = `#0A0F0D`.
- `test_brandbook_congelado_presente_e_integro`: recomputa SHA256 do congelado no repo.

## 8. Evidência de segurança

```
FROZEN_BRAND_RESPEITADO=YES   (congelado copiado verbatim; SHA256 confere)
NO_INVENTED_IDENTITY=YES      (0 resíduo de #1B73E8/#34A853 no site e brandbook)
LOCAL_FIRST=YES               (fontes do sistema, sem CDN externo)
NO_DEPLOY / NO_PUSH / NO_TAG / NO_RELEASE / NO_PYPI = YES
FORBIDDEN_FILES_INTACT=YES
HUMAN_APPROVAL_REQUIRED=YES
```

## 9. Limitações honestas

- Verificação visual do `index.html` baseada na reutilização exata dos tokens CSS do
  `brandbook_nomos.html` congelado + render do og-image (visualizado). Não houve captura
  de tela renderizada da página completa neste ambiente.
- JetBrains Mono não é embarcada (local-first): usa-se a stack monospace do sistema; em
  máquinas sem JetBrains Mono o navegador cai no fallback (IBM Plex Mono/SF Mono/Menlo).
- `docs/brand/NOMOS_BRANDBOOK.md` é guia expandido; o congelado v1.0 prevalece.

## 10. Próximo passo recomendado

Fazer o `nomos_update_agent --diff` também detectar deriva de marca (ex.: cor fora da
paleta congelada no site) como proposta low-risk, reforçando o congelamento via o próprio
agente — mantendo proposal-only.
