# CLAUDE_MEMORY_USAGE — protocolo de memória para o Claude Code / NOMOS

Como o agente (Claude Code, OpenClaw, NOMOS) deve **consultar** e **propor**
memória usando o [NOMOS Memory Engine](NOMOS_MEMORY_ENGINE.md). O motor é
**dry-run por padrão** e **fail-closed**: o agente propõe, o humano aprova.

## Ao INICIAR uma sessão

1. **Carregar contexto local** (leitura, não grava nada):

   ```bash
   python -m nomos.memory.cli --context
   ```

2. **Ler o handoff mais recente** — no bloco de contexto ele aparece como
   `➤ Último handoff: …`. É o ponto de retomada da missão anterior.
3. **Confirmar o escopo** da missão atual com o operador antes de agir.
4. **Não assumir contexto sem evidência.** Se a memória está vazia ou não cobre o
   assunto, diga isso — não invente estado anterior.

## Ao FINALIZAR uma missão relevante

1. **Gerar um resumo objetivo** do que mudou (arquivos, decisões, próximos passos).
2. **Propor a memória em DRY-RUN primeiro** (não grava):

   ```bash
   python -m nomos.memory.cli --add "MC28: NOMOS Memory Engine entregue; \
       motor local em src/nomos/memory; 52 testes; próximo: wire no CLI principal" \
       --source mission_result --scope project --priority high --tags "mc28,memoria"
   ```

3. **Revisar** a proposta. Só então **gravar com `--apply`** — e apenas se a
   política aprovar. Se vier `MEMORY_REJECTED_FAIL_CLOSED`, **não** contorne:
   reescreva a memória sem o conteúdo sensível.
4. **Gerar um handoff** claro para a próxima sessão:

   ```bash
   python -m nomos.memory.cli --add "HANDOFF: <estado atual>, <bloqueios>, \
       <próximo passo>" --source handoff --scope project --priority high --apply
   ```

## Quando PROPOR memória

- Decisões arquiteturais e o **porquê** delas.
- Preferências estáveis do operador (idioma, formato de entrega, tom).
- Resultado de missão e **próximo passo** (para retomar sem reconstruir tudo).
- Fatos de projeto duráveis (nomes, caminhos, contratos, convenções).

## Quando NÃO gravar (rejeitar)

- Qualquer **segredo**: API key, token, senha, chave privada/SSH, cookie, JWT.
- **Dados pessoais sensíveis**: CPF, CNPJ, dados bancários, cartão, seed phrase.
- **Comandos destrutivos** (`rm -rf`, `curl … | sh`, etc.).
- Conteúdo efêmero/ruído que não ajuda a próxima sessão.

Se tiver dúvida, **não grave** — a política já bloqueia, mas o julgamento do
agente é a primeira barreira.

## Regras invioláveis

- **Nunca** grave sem `--apply` **e** aprovação da política.
- **Nunca** salve segredo ou dado sensível — nem "só para lembrar".
- **Nunca** sobrescreva o histórico bruto. Compactar (`--compact --apply`) só
  cria o arquivo **derivado**; o bruto (`memory.jsonl`) é imutável por design.
- **Sempre** valide a integridade quando desconfiar de edição manual:

  ```bash
  python -m nomos.memory.cli --validate   # saída 0 = íntegro; 4 = adulterado
  ```

- **Sempre** gere evidência ao fechar trabalho relevante:

  ```bash
  python -m nomos.memory.cli --report --apply   # grava em ~/.nomos/memory/reports/
  ```

## Resumo do fluxo

```
início  → --context → ler handoff → confirmar escopo
trabalho→ (missão)
fim     → --add (dry-run) → revisar → --add --apply → --add handoff --apply → --report --apply
```
