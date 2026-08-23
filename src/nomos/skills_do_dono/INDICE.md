# Skills do dono, convertidas para o NOMOS

<!-- ARQUIVO GERADO. Não edite à mão:
     python3 tools/gerar_indice_skills.py
     O estado vem de `skill_catalogo.capacidades`, que o deriva do
     manifesto. Editar aqui faz o índice divergir do produto — foi
     exatamente o que aconteceu antes, com 13 linhas dizendo
     'falta chave' onde faltava o código. -->

**33 capacidades** no catálogo: **16** com código publicado e **17** em preparação.

Estado e risco NÃO são escritos aqui: vêm do catálogo, que os deriva
do manifesto. *Em preparação* significa que o manifesto ainda não
publica arquivo com checksum — sem isso não há o que verificar, e o
instalador recusa. Não é falta de chave nem de conta paga.

| skill | risco | estado | permissões | o que faz |
|---|---|---|---|---|
| `busca-arquivos` | baixo | vem no NOMOS | A0_READ_LOCAL | procura arquivos por nome e conteúdo numa pasta (só leitura) |
| `citeguard-retractions-sync` | alto | vem no NOMOS | A1_WRITE_LOCAL, A2_NET_EGRESS | baixa ~65 MB do Retraction Watch UMA VEZ; sem isso citacao retratada sai WARN, nao FAIL |
| `citeguard-selfcheck` | medio | vem no NOMOS | A0_READ_LOCAL, A1_WRITE_LOCAL | roda o harness golden-master do citeguard (46 casos) sem tocar a rede |
| `citeguard-verify-offline` | medio | vem no NOMOS | A0_READ_LOCAL, A1_WRITE_LOCAL | verifica citacoes SEM sair para a rede: DOI/arXiv malformado, placeholder, host privado |
| `citeguard-verify-online` | alto | vem no NOMOS | A0_READ_LOCAL, A1_WRITE_LOCAL, A2_NET_EGRESS | resolve DOI no Crossref e arXiv id no export.arxiv.org; manda cada DOI citado para terceiros |
| `hf-photoshoot-pessoa` | alto | vem no NOMOS · em preparação (sem código publicado) | A0_READ_LOCAL, A1_WRITE_LOCAL, A2_NET_EGRESS, A3_CRED_USE | poe SEMELHANCA DE PESSOA em peca paga (modelo vestindo, closeup com maos); instale so se aceitar isso |
| `hf-photoshoot-produto` | alto | vem no NOMOS · em preparação (sem código publicado) | A0_READ_LOCAL, A1_WRITE_LOCAL, A2_NET_EGRESS, A3_CRED_USE | fotos de produto sem rosto humano: hero, carrossel, moodboard, conceitual; GASTA DINHEIRO |
| `hf-photoshoot-restyle` | alto | vem no NOMOS · em preparação (sem código publicado) | A0_READ_LOCAL, A1_WRITE_LOCAL, A2_NET_EGRESS, A3_CRED_USE | reestiliza imagem que JA EXISTE no seu disco — unico modo cujo insumo obrigatorio e arquivo seu |
| `higgsfield-bootstrap` | alto | vem no NOMOS · em preparação (sem código publicado) | A1_WRITE_LOCAL, A2_NET_EGRESS, A5_CODE_EXEC, A5_SKILL_INSTALL | instala o CLI da Higgsfield via 'curl \| sh' SEM CHECKSUM — autorize UMA vez, aqui, em vez de 4 portas |
| `higgsfield-brandkit` | alto | vem no NOMOS · em preparação (sem código publicado) | A1_WRITE_LOCAL, A2_NET_EGRESS, A3_CRED_USE | importa identidade de marca de URL ARBITRARIA de terceiro e a persiste na conta; colide com a LEI DA MARCA (exige brand-resolve --require-official rc=0) |
| `higgsfield-dtc-ads` | alto | vem no NOMOS · em preparação (sem código publicado) | A0_READ_LOCAL, A1_WRITE_LOCAL, A2_NET_EGRESS, A3_CRED_USE | Marketing Studio: anuncios e UGC; GASTA DINHEIRO por chamada |
| `higgsfield-marketplace-cards` | alto | vem no NOMOS · em preparação (sem código publicado) | A0_READ_LOCAL, A1_WRITE_LOCAL, A2_NET_EGRESS, A3_CRED_USE | cards de marketplace; um comando so, nao ha o que separar; GASTA DINHEIRO |
| `higgsfield-media` | alto | vem no NOMOS · em preparação (sem código publicado) | A0_READ_LOCAL, A1_WRITE_LOCAL, A2_NET_EGRESS, A3_CRED_USE | gera imagem/video pela API paga da Higgsfield; GASTA DINHEIRO por chamada e nao ha nivel A que cubra custo |
| `higgsfield-soul-id` | alto | vem no NOMOS · em preparação (sem código publicado) | A0_READ_LOCAL, A1_WRITE_LOCAL, A2_NET_EGRESS, A3_CRED_USE | TREINA MODELO COM O ROSTO DE UMA PESSOA: envia 5 a 20 fotos para SaaS pago de terceiro; dado biometrico |
| `higgsfield-virality` | alto | vem no NOMOS · em preparação (sem código publicado) | A0_READ_LOCAL, A1_WRITE_LOCAL, A2_NET_EGRESS, A3_CRED_USE | analisa viralidade: FAZ UPLOAD de video seu e devolve texto — nao gera midia, fluxo de dados invertido |
| `higgsfield-workflows` | alto | vem no NOMOS · em preparação (sem código publicado) | A0_READ_LOCAL, A1_WRITE_LOCAL, A2_NET_EGRESS, A3_CRED_USE | draw_to_video e reframe: transforma esboco/video existente; GASTA DINHEIRO por chamada |
| `lembrete` | baixo | vem no NOMOS | A0_READ_LOCAL | formata um lembrete estruturado para a memoria do NOMOS |
| `organizador` | baixo | vem no NOMOS | A0_READ_LOCAL | relata os arquivos de uma pasta (contagem por tipo e maiores) |
| `paper-audit-core` | medio | vem no NOMOS | A0_READ_LOCAL, A1_WRITE_LOCAL | compara claims de um paper com o codigo de um repo JA clonado; nao baixa nada |
| `reach-bilibili` | alto | vem no NOMOS | A1_WRITE_LOCAL, A2_NET_EGRESS | metadados de video do Bilibili (titulo, autor, duracao, views) pela API web aberta — sem bili, sem login, stdlib pura |
| `reach-exa-search` | alto | vem no NOMOS · em preparação (sem código publicado) | A1_WRITE_LOCAL, A2_NET_EGRESS, A3_CRED_USE, A3_CONNECTOR_USE | busca semantica pela Exa via proxy MCP |
| `reach-github` | alto | vem no NOMOS | A0_READ_LOCAL, A1_WRITE_LOCAL, A2_NET_EGRESS, A3_CRED_USE | busca codigo e repositorios pelo gh CLI; usa o token do host (escopo repo+workflow) |
| `reach-linkedin` | alto | vem no NOMOS · em preparação (sem código publicado) | A1_WRITE_LOCAL, A2_NET_EGRESS, A3_CRED_USE, A3_CONNECTOR_USE | LinkedIn via servidor MCP scraper com estado de login proprio |
| `reach-readpage` | alto | vem no NOMOS | A1_WRITE_LOCAL, A2_NET_EGRESS | le uma pagina web via r.jina.ai — ATENCAO: um TERCEIRO ve toda URL que voce ler |
| `reach-reddit` | alto | vem no NOMOS | A1_WRITE_LOCAL, A2_NET_EGRESS | posts publicos de um subreddit (hot/new/top/rising) pela listagem .json aberta — sem rdt, sem login, stdlib pura |
| `reach-rss` | alto | vem no NOMOS | A1_WRITE_LOCAL, A2_NET_EGRESS | le feeds RSS/Atom falando DIRETO com a origem; nenhum intermediario ve o que voce le |
| `reach-transcribe` | alto | vem no NOMOS · em preparação (sem código publicado) | A0_READ_LOCAL, A1_WRITE_LOCAL, A2_NET_EGRESS, A3_CRED_USE | transcreve audio por API (Groq/OpenAI); separada para que reach-youtube-meta nao arraste exigencia de chave |
| `reach-twitter` | alto | vem no NOMOS · em preparação (sem código publicado) | A1_WRITE_LOCAL, A2_NET_EGRESS, A3_CRED_USE, A3_CONNECTOR_USE | Twitter/X via CLI de terceiro; cookies de autenticacao em texto |
| `reach-v2ex` | alto | vem no NOMOS | A1_WRITE_LOCAL, A2_NET_EGRESS, A5_CODE_EXEC | topicos quentes do V2EX por API publica, sem login |
| `reach-xhs` | alto | vem no NOMOS · em preparação (sem código publicado) | A1_WRITE_LOCAL, A2_NET_EGRESS, A3_CRED_USE, A3_CONNECTOR_USE | Xiaohongshu via CLI de terceiro com sessao logada de navegador |
| `reach-xiaoyuzhou` | alto | vem no NOMOS · em preparação (sem código publicado) | A0_READ_LOCAL, A1_WRITE_LOCAL, A2_NET_EGRESS, A3_CRED_USE, A5_CODE_EXEC | podcast Xiaoyuzhou: baixa e transcreve; depende de reach-transcribe |
| `reach-youtube-meta` | alto | vem no NOMOS | A1_WRITE_LOCAL, A2_NET_EGRESS | metadados de video do YouTube (titulo, canal, thumbnail) pelo oEmbed aberto — sem chave, sem yt-dlp, stdlib pura |
| `sistema-info` | baixo | vem no NOMOS | A0_READ_LOCAL | mostra Python, sistema e espaco em disco (so leitura) |

Risco é **derivado das permissões** quando o manifesto não declara
`risk_level` — hoje nenhum declara. A2 (rede) e A3 (credencial)
puxam para `alto`, então quase tudo que sai da máquina é alto.
