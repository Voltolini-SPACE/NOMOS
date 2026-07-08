# Roadmap — MCP, Ligações e Conexões

> Plano para levar as **conexões do NOMOS** ao próximo nível — mais conectores,
> **entrada** (não só saída), descoberta e automação — **sem abrir mão de uma
> única regra da casa**. Este documento é fiel ao código atual (mapeado em
> `src/nomos/interface/mcp_*.py`, `examples/mcp/*`, `src/nomos/simple/rotinas.py`,
> `src/nomos/kernel/{policy,approvals}.py`). Nada aqui é promessa vazia: cada
> item aponta o *seam* real de extensão.

## Princípios inegociáveis (o que NÃO muda)

- **Local por lei / stdio-only** — o subsistema MCP não abre socket; servidor e
  conectores são subprocessos falando stdin/stdout. Rede é opt-in.
- **A3 sempre com gate** — toda tool de conector é A3 → `REQUIRE_APPROVAL`. Sem
  aprovador humano (TTY ou fila do painel, token single-use, TTL 5 min), nada sai.
- **Fail-closed em cascata** — manifesto torto, tool desconhecida (herda o padrão,
  cujo padrão é A5), catálogo corrompido ⇒ recusa.
- **Credenciais só por env**, nunca em arquivo; redação ativa em erros/logs.
- **Confiança por SHA-256** do manifesto canônico (trust-by-registro, auditável).
- **Nunca finge** — sem bibliotecas não-oficiais que se passam por apps; sem
  webhook público que exponha porta e quebre o local-first.

## Onde estamos (estado real)

**Construído e testado:** servidor MCP só-leitura (5 tools A0 p/ Claude Desktop e
IDEs); cliente MCP stdio one-shot com mapa de risco A0–A6 e A5 fail-closed;
trust store SHA-256 (`mcp_catalogo.json`, 0600); **3 conectores** —
`telegram-bot` (envia **e lê** via `telegram_atualizacoes`/getUpdates),
`whatsapp-cloud` (só envio, Cloud API oficial), `email-smtp` (só envio, STARTTLS);
briefing em `Telegram/WhatsApp/e-mail` via dict `_CANAIS`; gate A3 + fila de
aprovação single-use; hub de conexões no painel (leitura pura).

**Lacunas (o que trava o "próximo nível"):**

1. **Quase tudo é saída, não entrada.** Receber só existe no Telegram (polling
   manual sob demanda). Sem IMAP, sem polling agendado, sem consumo do que chega.
2. **Só 3 conectores.** Instagram/TikTok mapeados (dependem de app oficial). Nada
   de Slack, Discord, Signal, calendário.
3. **Conectores invisíveis no `pip install`** — `conectores_exemplo()` só acha a
   pasta `examples/mcp` do repo/sdist; no **wheel instalado retorna `[]`** (bug
   já anotado em `_raiz_exemplos`). Quem instala não descobre nem os 3 que existem.
4. **Sem descoberta/registry** — confiar é sempre manual, arquivo por arquivo, e
   só por TTY (digitar "CONFIO"); o painel só mostra o comando para copiar.
5. **`A3_CONNECTOR_USE` inutilizado** — a categoria "conector" existe na política,
   mas o caminho MCP rotula tudo como `A3_CRED_USE` (rótulo menos fiel).

---

## Fase 1 — Fundação (quick wins, baixo risco, alto impacto)

| # | Melhoria | Seam (onde mexer) |
|---|---|---|
| 1.1 | **Empacotar os conectores no wheel** — hoje `nomos mcp exemplos` volta vazio pra quem instala por pip. Enviar `examples/mcp/**` como dados do pacote e fazer `_raiz_exemplos` achar a cópia instalada. | `pyproject.toml` (data files) + `mcp_catalogo._raiz_exemplos` + teste que valida descoberta fora do repo |
| 1.2 | **Taxonomia honesta** — rotear tools de conector por `A3_CONNECTOR_USE` (categoria que já existe) em vez de `A3_CRED_USE`. | `mcp_client.NIVEIS` + `kernel/policy.py` |
| 1.3 | **`nomos mcp doutor`** — check-up por conector: alcançável? credencial presente no env? (sem **jamais** imprimir o valor). Read-only, no espírito do `nomos doutor`. | `cli.cmd_mcp` + novo helper em `mcp_catalogo` |

**Recomendado começar por 1.1** — é o de maior impacto imediato (destrava os 3
conectores para todos os usuários instalados) e é um bug real.

## Fase 2 — Largura: novos conectores

Cada conector é um **exemplo isolado** seguindo o esqueleto atual
(`examples/mcp/<nome>/{manifesto.json,servidor.py}`, stdlib quando possível,
stdio, `nivel_padrao:"A3"`, credenciais por env, redação, teste com API mockada
**sem rede**). Aparece sozinho em `nomos mcp exemplos` e no hub do painel via o
glob de `conectores_exemplo()` — sem tocar em mais nada.

- **Signal** (via `signal-cli` **local**) — o mais alinhado ao local-first: nada
  passa por nuvem de terceiros.
- **Slack** — envio via webhook/API; leitura opcional.
- **Discord** — envio via webhook.
- **Calendário (CalDAV / `.ics` local)** — **ler** a agenda (entrada para o briefing).
- **IMAP (`email-imap`)** — **ler** a caixa de entrada (pull, sem endpoint público).

## Fase 3 — Entrada (a maior lacuna): receber sem quebrar o local-first

- **Polling de entrada agendado** — rotina que consome `telegram_atualizacoes`
  (getUpdates) num horário e monta "o que chegou", com aprovação. Usa a tool que
  **já existe**. Seam: nova ação de rotina + consumo em `rotinas.py`.
- **Triagem de e-mail** — sobre o conector `email-imap` (Fase 2): resumo dos
  não-lidos, tudo local, A3.
- **Abstração "ler"** — conectores declaram uma tool de leitura; rotinas podem
  consumi-la genericamente. **Tudo pull** (polling/IMAP), nunca webhook público.

## Fase 4 — Briefing/automação 2.0 (junta entrada + saída)

- Briefing com **"o que chegou"** (não-lidos, top mensagens) além do "seu dia".
- Novos canais no dict `_CANAIS` (Slack/Discord/Signal) — seam já genérico.
- Fluxo de **duas vias**: digest do que chegou → você responde, cada envio no gate A3.

## Fase 5 — Descoberta, catálogo e trust UX

- **Índice de conectores embarcado** (curado) — `nomos mcp buscar <termo>` acha
  conectores sem caçar arquivo. Só lista os oficiais empacotados; confiar segue manual.
- **Confiar pela fila do painel** — aprovar a confiança de um conector via a fila
  de aprovação (single-use, TTL), não só por TTY. Mantém o gate.
- **Assinatura opcional de autor** do manifesto (verificação destacada) como
  camada *acima* do SHA-256 — protege contra manifesto malicioso, não só troca.

## Fase 6 — Robustez / performance

- **Reuso de sessão** (pooling) para várias chamadas seguidas — mantendo fail-closed
  e o encerramento limpo do subprocesso.
- **Saúde de conectores** no `nomos doutor`/painel: alcançabilidade sem vazar credencial.

---

## O que NÃO vamos fazer (isto é a marca)

- **Nada de bibliotecas não-oficiais** que se passam por Instagram/TikTok/WhatsApp-web
  (violam ToS, derrubam contas). Instagram/TikTok **só** com app oficial aprovado.
- **Nada de webhook público** que exponha porta e quebre o local-first — entrada é
  sempre **pull** (polling/IMAP) ou API oficial que **você** controla.
- Nada de nuvem/rede sem opt-in; nada de credencial em arquivo; nada de bypass do gate.

## Priorização recomendada (impacto × esforço × alinhamento)

1. **Fase 1.1** (empacotar conectores) — destrava tudo para usuários instalados. Já.
2. **Signal (Fase 2)** + **entrada agendada (Fase 3)** — diferencial local-first forte.
3. **`nomos mcp doutor` (1.3)** e **taxonomia (1.2)** — polimento honesto de baixo risco.
4. Descoberta e trust-UX (Fase 5) quando houver ≥ 5–6 conectores.

Cada item entra pelo ciclo `implementation-loop-100`: SPEC → implementar em
passos pequenos → testes reais (API mockada, sem rede) → ruff/gate → evidência →
commit. Sem afrouxar nenhuma trava.
