# NOMOS ↔ Telegram (conector MCP oficial)

Ponte **governada** entre o NOMOS e a [Bot API oficial do Telegram](https://core.telegram.org/bots/api).
Zero dependências, zero bibliotecas não-oficiais, zero token em arquivo.

## O que dá para fazer

| Tool | O quê | Nível |
|---|---|---|
| `telegram_quem_sou` | valida o token, mostra a identidade do bot | A3 |
| `telegram_enviar` | envia texto para um chat/canal | A3 |
| `telegram_atualizacoes` | lê as mensagens recebidas pelo bot | A3 |

Toda tool usa **credencial + rede** ⇒ nível **A3**: o NOMOS pede a **sua**
aprovação a cada chamada. Em scripts/CI a resposta é sempre "não" (fail-closed).

## Passo a passo (5 minutos)

```bash
# 1) no Telegram, fale com @BotFather → /newbot → copie o token
# 2) o token vive SÓ no ambiente (nunca em arquivo):
export NOMOS_TELEGRAM_TOKEN="123456:ABC-DEF..."

# 3) registre a confiança neste manifesto (impressão SHA-256):
nomos mcp confiar examples/mcp/telegram/manifesto.json

# 4) valide a ponta a ponta:
nomos mcp chamar examples/mcp/telegram/manifesto.json telegram_quem_sou '{}'

# 5) mande a primeira mensagem (abra chat com o bot antes e dê /start):
nomos mcp chamar examples/mcp/telegram/manifesto.json \
  telegram_enviar '{"chat_id": "SEU_CHAT_ID", "texto": "oi do NOMOS 🔒"}'

# dica: seu chat_id aparece em telegram_atualizacoes depois do /start
nomos mcp chamar examples/mcp/telegram/manifesto.json telegram_atualizacoes '{}'
```

## As leis da casa, aqui

- **Sem token ⇒ nada funciona** — o servidor conecta e lista tools, mas
  cada chamada falha fechado com a instrução do que fazer. Nunca finge.
- **O token jamais aparece** em erros, logs ou respostas (redação ativa).
- **Manifesto alterado ⇒ confiança cai** para experimental (impressão muda).
- Este conector **não lê nem escreve nada** no seu disco.
