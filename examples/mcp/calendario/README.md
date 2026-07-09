# Conector NOMOS ↔ Calendário (.ics local) — leitura da sua agenda

**Entrada 100% local-first e só-leitura.** O NOMOS lê os eventos de um arquivo
`.ics` que você exportou do seu app de calendário (biblioteca padrão do Python,
sem dependências). **Não toca a internet**: só abre um arquivo no seu disco.

## Como conseguir o `.ics`

Exporte a sua agenda para um arquivo local:

- **Google Agenda**: Configurações → Importar e exportar → Exportar (gera um `.ics`).
- **Apple Calendar**: Arquivo → Exportar → Exportar…
- **Outlook**: Arquivo → Salvar Calendário.

Depois aponte o NOMOS para ele (só por ambiente — nunca embutido):

```bash
export NOMOS_ICS_PATH="$HOME/agenda.ics"
```

## Ligar no NOMOS

```bash
nomos mcp confiar calendario                       # por nome (ou o caminho do manifesto)
nomos mcp chamar calendario calendario_quem_sou '{}'
nomos mcp chamar calendario calendario_hoje '{}'
nomos mcp chamar calendario calendario_proximos '{"limite": 5}'
```

## As leis da casa

- **A0** nas tools de leitura (ler um arquivo local não é conta conectada nem
  credencial — seria desonesto rotular de outra forma). Mesmo assim, o conector
  **precisa ser confiado** (`nomos mcp confiar calendario`) antes de qualquer
  chamada; sem confiança, o NOMOS nem abre este processo. Tool não declarada cai
  no `nivel_padrao` **A5** (fail-closed).
- **Só leitura de verdade**: abre o `.ics` em modo leitura e **nunca** escreve,
  altera, move ou apaga o arquivo.
- O caminho vem só de `NOMOS_ICS_PATH`; sem ele (ou arquivo inexistente), tudo
  **falha fechado** com instrução — nunca finge. Em `quem_sou` aparece só o nome
  do arquivo, não o caminho completo.
- Entende `.ics` padrão (RFC 5545): dobra de linhas, eventos de dia inteiro
  (`YYYYMMDD`), horários locais e em UTC (`…Z`, convertido para o seu fuso).
