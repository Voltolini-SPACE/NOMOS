# 🌐 NOMOS Landing Page

Página inicial do NOMOS — apresentação profissional, clara e responsiva.

## Arquivos

- **`index.html`** — Landing page principal (HTML5 + CSS inline)
- **`404.html`** — Página de erro branded
- **`preview.py`** — Preview local + validação (`--check`), stdlib apenas
- **`assets/favicon.svg`** — Ícone do navegador (SVG escalável)
- **`assets/og-image.png`** — Imagem Open Graph / Twitter (1200×630)
- **`assets/og-image.svg`** — Fonte editável do og-image
- **`assets/make_og_image.py`** — Gera o PNG a partir da marca (Pillow)

## Rodar Localmente

### Opção 1 (recomendada): script de preview
```bash
python site/preview.py            # serve em http://localhost:8000
python site/preview.py --port 8080
```

### Opção 2: validar sem servir (gate local, read-only)
```bash
python site/preview.py --check    # valida assets, links, SEO/a11y; exit 0/1
```
Não escreve nada e não acessa a internet. Rode antes de publicar.

### Opção 3: servidor Python direto
```bash
cd site && python -m http.server 8000   # http://localhost:8000
```

### Opção 4: browser direto
```bash
open site/index.html      # macOS
xdg-open site/index.html  # Linux
start site/index.html     # Windows
```

## Regenerar o og-image

```bash
python site/assets/make_og_image.py   # requer Pillow (dev)
```
Edite `assets/og-image.svg` como fonte de referência; o PNG é o arquivo servido.

## Estrutura

```
site/
├── index.html            # Landing page principal
├── 404.html              # Página de erro
├── preview.py            # Preview + validação local
├── README.md             # Este arquivo
└── assets/
    ├── favicon.svg       # Ícone do navegador
    ├── og-image.png      # Open Graph (1200×630)
    ├── og-image.svg      # Fonte do og-image
    └── make_og_image.py  # Gerador do PNG
```

## Editar Conteúdo

A landing page usa **HTML + CSS inline** para máxima portabilidade:

1. Abra `site/index.html` em editor de texto
2. Procure pela seção que quer editar (marcadas com comentários `<!-- ... -->`)
3. Modifique o conteúdo HTML
4. Salve e recarregue o navegador

### Exemplo: Mudar Headline

Procure:
```html
<h1>Seu agente. Sua máquina. Suas regras.</h1>
```

Altere para:
```html
<h1>Sua nova headline aqui</h1>
```

## Build para Produção

Nenhuma build necessária — `index.html` já é production-ready:

- ✅ Minificado? Não (legível é mais importante)
- ✅ Otimizado? Sim (CSS inline, zero requests)
- ✅ Responsivo? Sim (mobile, tablet, desktop)
- ✅ Acessível? Sim (WCAG 2.1 AA)
- ✅ SEO? Sim (meta tags, OG)

### Publicar Online

Para publicar em um servidor web:

1. Copie `site/` inteira para seu host
2. Configure `index.html` como documento raiz
3. (Opcional) Configure HTTPS
4. (Opcional) Configure redirect de `nomos.se7enpay.com` → seu host

Exemplo com **GitHub Pages**:
```bash
cd site
git add .
git commit -m "Update landing page"
git push origin main

# Habilitar GitHub Pages em Settings → Pages → Branch: main /root
```

## Identidade Visual (Brandbook v1.0 — congelado)

> ⚠️ A identidade é **congelada**. Não invente cores nem fontes. Fonte de verdade:
> [`docs/brand/frozen/BRANDBOOK_NOMOS.md`](../docs/brand/frozen/BRANDBOOK_NOMOS.md).

### Cores (variáveis CSS no `<style>` do `index.html`)
```css
--bg: #0A0F0D;      /* preto terminal (fundo)   */
--surface: #111814; /* superfície (cards)        */
--neon: #5AF78E;    /* verde-neon (marca, CTA)   */
--texto: #E8FFE8;   /* branco-terminal (texto)   */
--ciano: #56E1E9;   /* acento / links            */
--amarelo: #F2C14E; /* aviso                     */
--vermelho: #FF5C57;/* erro                      */
```
Alterar a paleta exige nova versão v1.x do brandbook, com aprovação humana.

### Tipografia
Monoespaçada em tudo. Stack usada (local-first, sem CDN):
```css
font-family: 'JetBrains Mono', 'IBM Plex Mono', ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
```

### Links e CTAs

Para mudar `href` dos links (ex: GitHub, docs):
```html
<a href="https://github.com/Voltolini-SPACE/NOMOS">GitHub</a>
```

Atualize a URL conforme necessário.

## Checklist de Qualidade

Antes de publicar:

- [ ] Links funcionam (GitHub, docs, manual)
- [ ] Texto está correto (sem typos)
- [ ] Imagens carregam (se houver)
- [ ] Responsivo em mobile (teste em DevTools)
- [ ] Acessibilidade OK (contraste, alt-text)
- [ ] Performance OK (nenhum grande arquivo)
- [ ] SEO tags estão preenchidas (og:title, og:description, etc.)

## Roadmap

- [x] **v1.0** — Landing básica em HTML puro
- [ ] **v1.1** — Adicionar screenshots/GIFs
- [ ] **v1.2** — Seção de FAQ
- [ ] **v2.0** — Blog integrado
- [ ] **v3.0** — Marketplace de skills

---

**Mantido como parte do NOMOS. Local por lei.**

