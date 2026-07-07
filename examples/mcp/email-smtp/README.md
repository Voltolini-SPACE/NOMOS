# NOMOS ↔ E-mail (conector MCP via SMTP)

O **terceiro canal** do briefing, ao lado de Telegram e WhatsApp. Envia
e-mail pelo **seu** servidor SMTP usando só a biblioteca padrão do Python
(`smtplib`) — zero dependências, zero serviço de terceiros.

## O que dá para fazer

| Tool | O quê | Nível |
|---|---|---|
| `email_quem_sou` | conecta e autentica (sem enviar), mostra o remetente | A3 |
| `email_enviar` | envia um e-mail de texto | A3 |

Toda tool usa **credencial + rede** ⇒ nível **A3**: o NOMOS pede a **sua**
aprovação a cada chamada.

## Configuração (credenciais só no ambiente)

```bash
export NOMOS_SMTP_HOST="smtp.seuprovedor.com"
export NOMOS_SMTP_PORT="587"                 # 587 = STARTTLS (padrão)
export NOMOS_SMTP_USER="voce@dominio.com"
export NOMOS_SMTP_PASSWORD="sua-app-password"
export NOMOS_SMTP_FROM="voce@dominio.com"    # opcional; padrão = USER

nomos mcp confiar examples/mcp/email-smtp/manifesto.json
nomos mcp chamar examples/mcp/email-smtp/manifesto.json email_quem_sou '{}'
nomos mcp chamar examples/mcp/email-smtp/manifesto.json \
  email_enviar '{"destinatario":"voce@dominio.com","assunto":"oi","texto":"do NOMOS"}'
```

Gmail/Outlook: use uma **app password** (não a senha da conta). Porta 465
usa SSL direto; 587 usa STARTTLS.

## Briefing diário por e-mail

```bash
nomos rotinas criar "Briefing por e-mail" 08:00 briefing-email:voce@dominio.com
nomos rotinas agendar          # cole a linha (com --panel) no seu cron
```

## As leis da casa, aqui

- **Sem credenciais ⇒ nada funciona** — falha fechado com instrução.
- **A senha jamais aparece** em erros, logs ou respostas (redação ativa).
- **Recusa texto claro**: sem STARTTLS/SSL, o envio só ocorre com
  `NOMOS_SMTP_INSECURE=1` (opt-in explícito, para servidor local de teste).
- Este conector **não lê nem escreve nada** no seu disco.
