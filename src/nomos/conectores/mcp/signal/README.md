# Conector NOMOS ↔ Signal (via signal-cli)

Ponte **governada** e **local-first** com o Signal, usando o
[signal-cli](https://github.com/AsamK/signal-cli) — o cliente oficial de linha
de comando. Nada passa por nuvem de terceiros além do próprio Signal.

## Pré-requisitos (uma vez)

1. Instale o **signal-cli** (veja o repositório oficial acima).
2. Registre **ou** vincule a sua conta uma única vez, por exemplo:
   - vincular a um celular já existente: `signal-cli link -n "NOMOS"` (escaneie
     o QR no app do Signal), **ou**
   - registrar um número novo: `signal-cli -a +5511999999999 register`
     (e confirme com o código: `... verify CÓDIGO`).
3. Exporte o número da conta:
   ```bash
   export NOMOS_SIGNAL_NUMBER="+5511999999999"
   ```

## Ligar no NOMOS

```bash
nomos mcp confiar examples/mcp/signal/manifesto.json     # você digita "CONFIO"
nomos mcp chamar examples/mcp/signal/manifesto.json signal_quem_sou '{}'
nomos mcp chamar examples/mcp/signal/manifesto.json \
     signal_enviar '{"destino": "+5511888888888", "texto": "oi do NOMOS"}'
```

Para enviar a um grupo, passe o id do grupo e `"grupo": true`.

## As leis da casa

- **A3** em toda tool (credencial + rede): o NOMOS pede a sua aprovação a cada
  chamada — em script/CI a resposta é sempre "não".
- O número vem **só** de `NOMOS_SIGNAL_NUMBER`; nunca fica em arquivo e é
  **redigido** em erros. Nas respostas aparece mascarado (ex.: `+55****88`).
- Sem signal-cli ou sem o número, tudo **falha fechado** com instrução — nunca
  finge.
- O signal-cli é chamado como binário, **sem shell**.
