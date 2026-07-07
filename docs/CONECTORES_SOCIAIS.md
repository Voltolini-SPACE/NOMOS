# Conectores sociais via MCP — o mapa honesto

O NOMOS conversa com redes sociais **só por APIs oficiais**, sempre pelo
mesmo caminho governado: servidor MCP local → manifesto com nível de risco →
`nomos mcp confiar` → cada chamada passa pelo **gate de aprovação** (A3:
credencial + rede). Credenciais vivem **só no ambiente**, nunca em arquivo,
e jamais aparecem em logs ou erros (redação ativa, testada).

O que existe hoje, o que exige o quê, e o que **não** vamos fazer:

| Canal | Estado no NOMOS | O que você precisa | Limites honestos |
|---|---|---|---|
| **Telegram** | ✅ pronto (`examples/mcp/telegram/`) — enviar, ler, validar bot | criar bot no @BotFather (2 min, grátis) | bot só vê mensagens enviadas a ele |
| **WhatsApp** | ✅ envio pronto (`examples/mcp/whatsapp-cloud/`) — texto + template | conta Meta Business + app + número Cloud API (token + phone_id) | **receber** exige webhook público (fora do local-first); fora da janela de 24h, só template aprovado |
| **Instagram** | 📋 mapeado, não construído | conta business/creator + app Meta aprovado (Graph API) com `instagram_content_publish` | API só publica em conta business; DMs/feed pessoal não existem na API oficial |
| **TikTok** | 📋 mapeado, não construído | app aprovado no TikTok for Developers (Content Posting API) | aprovação de app é manual e restritiva; sem app aprovado não há API |

## Por que "mapeado, não construído" em vez de um conector que finge

Bibliotecas não-oficiais de WhatsApp/Instagram/TikTok operam simulando o
aplicativo ou raspando a web — isso **viola os termos de uso** e derruba
contas reais de usuários reais. O NOMOS nunca finge: quando a Meta ou o
TikTok aprovarem seu app, o desenho dos conectores acima (MCP + A3 +
credencial por ambiente) se aplica igual — o esqueleto do WhatsApp Cloud
serve de modelo direto para os dois.

## Receita padrão (vale para qualquer conector)

```bash
export NOMOS_TELEGRAM_TOKEN="..."            # credencial só no ambiente
nomos mcp confiar examples/mcp/telegram/manifesto.json
nomos mcp chamar examples/mcp/telegram/manifesto.json telegram_quem_sou '{}'
# toda chamada A3 abre o gate: VOCÊ aprova, a auditoria registra
```

Regras que valem para todos: manifesto alterado ⇒ confiança cai para
experimental; revogado ⇒ bloqueado; scripts/CI ⇒ resposta sempre "não";
conteúdo de mensagens não entra no painel (metadados apenas).
