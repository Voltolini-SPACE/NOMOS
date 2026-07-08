# Conector NOMOS ↔ E-mail (IMAP) — leitura da caixa

**Entrada por pull, local-first e só-leitura.** O NOMOS lê os cabeçalhos das
mensagens mais recentes da sua caixa por IMAP (biblioteca padrão do Python, sem
dependências), sem webhook público — é o NOMOS que puxa, quando você aprova.

## Credenciais (só por ambiente)

```bash
export NOMOS_IMAP_HOST="imap.gmail.com"      # ou imap-mail.outlook.com, etc.
export NOMOS_IMAP_USER="voce@exemplo.com"
export NOMOS_IMAP_PASSWORD="sua-app-password" # com 2FA, use uma app password
# opcionais:
export NOMOS_IMAP_PORT="993"                  # SSL por padrão
export NOMOS_IMAP_MAILBOX="INBOX"
```

## Ligar no NOMOS

```bash
nomos mcp confiar examples/mcp/email-imap/manifesto.json   # você digita "CONFIO"
nomos mcp chamar examples/mcp/email-imap/manifesto.json email_imap_quem_sou '{}'
nomos mcp chamar examples/mcp/email-imap/manifesto.json \
     email_imap_recentes '{"limite": 5, "nao_lidas": true}'
```

## As leis da casa

- **A3** em toda tool (credencial + rede): aprovação sua a cada chamada; em
  script/CI a resposta é sempre "não".
- **Só leitura de verdade**: seleciona a caixa em `readonly` e usa `BODY.PEEK` —
  **não marca como lido**, não apaga, não move, não envia.
- Senha só de `NOMOS_IMAP_PASSWORD`; nunca em arquivo, **redigida** em erros. A
  conta aparece mascarada (ex.: `jo***@ex***`).
- SSL por padrão (porta 993). Sem as variáveis, tudo **falha fechado** com
  instrução — nunca finge.
