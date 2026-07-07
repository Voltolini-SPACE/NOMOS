# NOMOS ↔ WhatsApp (Cloud API oficial — envio)

Conector MCP para a **WhatsApp Business Cloud API da Meta**. Só o caminho
oficial: nada de bibliotecas que simulam o aplicativo (violam os termos e
derrubam números).

## O que dá para fazer

| Tool | O quê | Nível |
|---|---|---|
| `whatsapp_enviar_texto` | texto na janela de 24h do contato | A3 |
| `whatsapp_enviar_template` | template aprovado (abre conversa) | A3 |

**Receber** mensagens exige webhook público — fora do desenho local-first;
este conector é de envio, e diz isso na cara.

## O que a Meta exige de você (sem atalho)

1. Conta **Meta Business** e app em developers.facebook.com (produto
   WhatsApp). O número de teste da Meta funciona para começar.
2. O **PHONE_NUMBER_ID** do número e um **ACCESS_TOKEN**.

```bash
export NOMOS_WHATSAPP_TOKEN="EAAG..."          # só no ambiente
export NOMOS_WHATSAPP_PHONE_ID="1234567890"

nomos mcp confiar examples/mcp/whatsapp-cloud/manifesto.json
nomos mcp chamar examples/mcp/whatsapp-cloud/manifesto.json \
  whatsapp_enviar_template '{"numero": "5511999998888", "template": "hello_world", "idioma": "en_US"}'
```

Sem as variáveis, toda chamada falha fechado com esta instrução. O token
jamais aparece em erros (redação ativa, coberta por teste).
