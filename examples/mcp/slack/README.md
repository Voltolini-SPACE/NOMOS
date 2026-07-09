# Conector NOMOS ↔ Slack — envio por Incoming Webhook

**Envio oficial, local-first e opt-in.** O NOMOS faz um POST de texto para o
**Incoming Webhook** do seu workspace (biblioteca padrão do Python, sem
dependências). Sem token de usuário, sem app não-oficial, sem browser.

## Criar o webhook (uma vez)

No Slack: **Apps → "Incoming WebHooks" → Add to Slack →** escolha o canal **→**
copie a URL (algo como `https://hooks.slack.com/services/T…/B…/…`). Essa URL é
**secreta** — quem a tem posta no seu canal.

```bash
export NOMOS_SLACK_WEBHOOK="https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXX"
```

## Ligar no NOMOS

```bash
nomos mcp confiar slack                        # por nome (ou o caminho do manifesto)
nomos mcp chamar slack slack_quem_sou '{}'     # confirma o webhook (mascarado), sem enviar
nomos mcp chamar slack slack_enviar '{"texto": "deploy verde ✅"}'
```

## As leis da casa

- **A3** em toda tool (credencial + rede): aprovação sua a cada chamada; em
  script/CI a resposta é sempre "não".
- A credencial (a **URL do webhook**) só vem de `NOMOS_SLACK_WEBHOOK`, nunca de
  arquivo, e é **redigida** em erros. Em `quem_sou` aparece mascarada.
- **Recuso apontar o envio para fora de `hooks.slack.com`** — a URL tem de ser
  um webhook do Slack, senão falha fechado (não vira um POST genérico).
- **Só envio**: receber exigiria um app/socket permanente — fora do desenho
  local-first. Está dito, não escondido.
- Sem a variável, tudo **falha fechado** com instrução — nunca finge que enviou.
