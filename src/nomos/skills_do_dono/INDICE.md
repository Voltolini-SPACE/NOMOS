# Skills do dono, convertidas para o NOMOS

29 manifestos, todos validados por `ext.skill_registry.validar_manifesto`.
Estado medido nesta máquina com `shutil.which` — não é promessa, é medição.

| skill | risco | estado | o que faz |
|---|---|---|---|
| `citeguard-retractions-sync` | alto | pronta (usa rede) | baixa ~65 MB do Retraction Watch UMA VEZ; sem isso citacao retratada sai WARN, nao FAIL |
| `citeguard-selfcheck` | medio | PRONTA · sem rede, sem chave | roda o harness golden-master do citeguard (46 casos) sem tocar a rede |
| `citeguard-verify-offline` | medio | PRONTA · sem rede, sem chave | verifica citacoes SEM sair para a rede: DOI/arXiv malformado, placeholder, host privado |
| `citeguard-verify-online` | alto | pronta (usa rede) | resolve DOI no Crossref e arXiv id no export.arxiv.org; manda cada DOI citado para terceiros |
| `hf-photoshoot-pessoa` | alto | falta chave | poe SEMELHANCA DE PESSOA em peca paga (modelo vestindo, closeup com maos); instale so se aceitar isso |
| `hf-photoshoot-produto` | alto | falta chave | fotos de produto sem rosto humano: hero, carrossel, moodboard, conceitual; GASTA DINHEIRO |
| `hf-photoshoot-restyle` | alto | falta chave | reestiliza imagem que JA EXISTE no seu disco — unico modo cujo insumo obrigatorio e arquivo seu |
| `higgsfield-bootstrap` | alto | pronta (usa rede) | instala o CLI da Higgsfield via 'curl | sh' SEM CHECKSUM — autorize UMA vez, aqui, em vez de 4 portas |
| `higgsfield-brandkit` | alto | falta chave | importa identidade de marca de URL ARBITRARIA de terceiro e a persiste na conta; colide com a LEI DA MARCA (exige brand-resolve --require-official rc=0) |
| `higgsfield-dtc-ads` | alto | falta chave | Marketing Studio: anuncios e UGC; GASTA DINHEIRO por chamada |
| `higgsfield-marketplace-cards` | alto | falta chave | cards de marketplace; um comando so, nao ha o que separar; GASTA DINHEIRO |
| `higgsfield-media` | alto | falta chave | gera imagem/video pela API paga da Higgsfield; GASTA DINHEIRO por chamada e nao ha nivel A que cubra custo |
| `higgsfield-soul-id` | alto | falta chave | TREINA MODELO COM O ROSTO DE UMA PESSOA: envia 5 a 20 fotos para SaaS pago de terceiro; dado biometrico |
| `higgsfield-virality` | alto | falta chave | analisa viralidade: FAZ UPLOAD de video seu e devolve texto — nao gera midia, fluxo de dados invertido |
| `higgsfield-workflows` | alto | falta chave | draw_to_video e reframe: transforma esboco/video existente; GASTA DINHEIRO por chamada |
| `paper-audit-core` | medio | PRONTA · sem rede, sem chave | compara claims de um paper com o codigo de um repo JA clonado; nao baixa nada |
| `reach-bilibili` | alto | falta binario | B站 via CLI de terceiro com sessao logada |
| `reach-exa-search` | alto | falta binario | busca semantica pela Exa via proxy MCP |
| `reach-github` | alto | falta chave | busca codigo e repositorios pelo gh CLI; usa o token do host (escopo repo+workflow) |
| `reach-linkedin` | alto | falta binario | LinkedIn via servidor MCP scraper com estado de login proprio |
| `reach-readpage` | alto | pronta (usa rede) | le uma pagina web via r.jina.ai — ATENCAO: um TERCEIRO ve toda URL que voce ler |
| `reach-reddit` | alto | falta binario | Reddit via CLI de terceiro com sessao logada |
| `reach-rss` | alto | pronta (usa rede) | le feeds RSS/Atom falando DIRETO com a origem; nenhum intermediario ve o que voce le |
| `reach-transcribe` | alto | falta chave | transcreve audio por API (Groq/OpenAI); separada para que reach-youtube-meta nao arraste exigencia de chave |
| `reach-twitter` | alto | falta binario | Twitter/X via CLI de terceiro; cookies de autenticacao em texto |
| `reach-v2ex` | alto | pronta (usa rede) | topicos quentes do V2EX por API publica, sem login |
| `reach-xhs` | alto | falta binario | Xiaohongshu via CLI de terceiro com sessao logada de navegador |
| `reach-xiaoyuzhou` | alto | falta binario | podcast Xiaoyuzhou: baixa e transcreve; depende de reach-transcribe |
| `reach-youtube-meta` | alto | pronta (usa rede) | metadados e legendas JA EXISTENTES de video do YouTube; nao transcreve, nao pede chave |

## Como ler o estado

- **PRONTA · sem rede, sem chave** — instala e usa hoje, sem sair da máquina.
- **pronta (usa rede)** — o binário está aqui; os dados saem da máquina.
- **falta chave** — o binário existe, falta credencial que só você pode fornecer.
- **falta binario** — declarado em `requires`; o instalador deve RECUSAR, não falhar no uso.

## O que não foi convertido, e por quê

- **`lit-review`** — o corpo dela é "Busca: WebSearch. Fetch: WebFetch. Paralelismo: Agent".
  Converter entregaria uma casca mandando o NOMOS usar ferramentas que ele não tem.
- **`agent-reach doctor` / `check-update` / `install`** — camada de auto-diagnóstico que só
  existia para rotear backends concorrentes. Depois do corte não sobra o que rotear.
