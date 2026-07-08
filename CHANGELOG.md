# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/). Datas em UTC.

## [Unreleased]

### Added (MC27-UX — Motor Council: `conselho ajuda` e `diagnostico --json`)
- **`nomos conselho ajuda`** e **`/conselho ajuda`**: mapa amigável dos 4
  comandos disponíveis (status, modos, diagnostico, simular) + a nota
  fail-closed. Estático e puro (fonte única em `cli_info`).
- **`conselho diagnostico --json`** (CLI e chat): a mesma leitura viva da trava
  em JSON versionado (`nomos.council.diagnostico.v1`, campos
  `real_engine_execution_enabled` / `fail_closed`) — para monitoramento e
  scripts. Teste monkeypatcha a trava e prova que o JSON acompanha.

### Added (MC26-UX — Motor Council: `conselho diagnostico` (leitura viva da trava))
- Novo `nomos conselho diagnostico` e `/conselho diagnostico`: **lê a trava
  `REAL_LOCAL_ENGINE_EXECUTION_ENABLED` ao vivo** (via `real_execution_enabled()`)
  e reporta o estado fail-closed — prova executável do "evidência, não promessa".
  Um teste monkeypatcha a trava e comprova que a saída **mudaria** se ela fosse
  ligada (logo, não é string fixa).
- Módulo novo `nomos.council.cli_diag`, puro por AST: importa só a LEITURA da
  trava e o contrato de flags proibidas; nunca chama `LocalExecutionHarness.execute`,
  não toca rede/subprocess/cloud/kernel/FS/env/tempo. A raiz `conselho`/`/conselho`
  agora lista os 4 comandos úteis (inclui `diagnostico`).

### Added (MC25-UX — Motor Council: `--json`, raiz útil, prova no site, badges)
- **`--json`** em `conselho status`/`modos` (CLI e chat): saída estável e
  versionada (`nomos.council.status.v1` / `nomos.council.modos.v1`) para
  scripts — fatos estáticos, sem interpolação de entrada.
- **Raiz mais útil:** `nomos conselho` e `/conselho` deixaram de mandar "leia
  só a doc" e agora apontam o que **já funciona** (`status`, `modos`,
  `simular`) — sem afrouxar nenhuma trava (`CLI/CHAT_ENABLED=false` e
  `REAL_*=false` seguem impressos).
- **Site:** terceiro terminal real na seção Prova com a saída de
  `nomos conselho status` (as travas `=false` como evidência do fail-closed).
- **README:** badges factuais (Python 3.10–3.13 = matriz do CI, licença MIT,
  local-first) ao lado do badge de CI que já existia.

### Added (MC24-UX — Motor Council: `status` e `modos` também no chat)
- `/conselho status` e `/conselho modos [--avancado]` finalizados no chat,
  simétricos à CLI e reusando a **fonte única** de texto (`cli_info`) — info
  pura, sem executar motor, ler prompt, tocar rede ou disco. `perguntar`/
  `revisar`/`explicar` seguem **fail-closed** nas duas superfícies; a trava
  `REAL_LOCAL_ENGINE_EXECUTION_ENABLED = False` continua intocada.
- Testes de chat atualizados (informativo em vez de desabilitado) + lock de
  recusa de flag proibida sem eco. UX spec, README e site alinhados.

### Added (MC23-UX — Motor Council: `status` e `modos` finalizados)
- `nomos conselho status` e `nomos conselho modos [--avancado]` saíram do
  esqueleto desabilitado e agora funcionam como comandos **puramente
  informativos**: imprimem fatos estáticos (estado das travas; os 4 modos)
  sem executar motor, ler prompt, tocar rede/disco ou construir
  policy/vault/audit. `perguntar`/`revisar` — que exigiriam execução real —
  seguem **fail-closed**, e a trava `REAL_LOCAL_ENGINE_EXECUTION_ENABLED =
  False` do harness permanece intocada.
- Novo módulo puro `nomos.council.cli_info` (só stdlib + contrato de flags
  proibidas), com pureza provada por AST e ~15 testes novos em
  `tests/council/test_cli_conselho_info.py` (sem eco de prompt, sem
  persistência, recusa de flags proibidas, não chama harness/orquestrador).
- README e docs atualizados para refletir o novo estado (docs ↔ código).

### Added (MC47 — Site: seção "Prova" com evidências reais)
- Nova seção `#prova` na landing: **saídas reais** do CLI embutidas como
  terminais (`nomos doutor`, `nomos mcp exemplos`), uma tira de prova técnica
  (CI 12/12 em 3 SO × 4 Pythons, cobertura, `SEC-01…12`, zero telemetria) e
  o card do **Motor Council** (honesto: dry-run/fail-closed). Hero ganhou a
  estatística `12/12` de CI. Nada inventado — travado por `tests/test_site_prova.py`,
  inclusive um teste que impede o marketing de anunciar mais testes do que
  existem no repositório.

### Fixed (MC46.5 — Windows: último teste, métrica de memória)
- Corrigidas as 2 causas raiz anteriores, sobrou **1 teste** no Windows:
  `test_health_tem_uptime` exigia `mem_pico_mb > 0`. A função `_mem_pico_mb`
  usa o módulo `resource` (exclusivo de Unix); no Windows ele não existe e
  a métrica degrada para `0.0` (comportamento correto — o produto não
  quebra, só omite a métrica). O teste era rígido demais: agora exige
  `> 0` só onde `resource` existe (Unix) e aceita `>= 0` no resto.
  Windows: 28 → 0 falhas, matriz completa (3 SO × 4 Pythons) verde.

### Fixed (MC46.4 — Windows: home directory sem USERPROFILE)
- **2ª causa raiz, revelada quando a 1ª foi corrigida** (o Python já
  bootava, mas o CLI estourava): `config.nomos_home()` avaliava o default
  `str(Path.home() / ".nomos")` de forma ANSIOSA — mesmo com `NOMOS_HOME`
  setado. Num ambiente sem as variáveis de home (Windows sem USERPROFILE,
  como no subprocesso dos testes), `Path.home()` levantava
  `RuntimeError: Could not determine home directory`. Agora a avaliação é
  preguiçosa: com `NOMOS_HOME`, `Path.home()` NEM é chamado — bug de
  produto real, corrigido, com teste de regressão (`test_config_home.py`).
- `tests/_cli_env.py` também passou a preservar as variáveis de home
  (USERPROFILE/HOMEDRIVE/HOMEPATH/HOME) — defesa em profundidade.

### Fixed (MC46.3 — Windows de volta: causa raiz corrigida)
- **Causa raiz das ~28 falhas de teste no Windows, achada no log real**
  (`gh run view --log-failed`): os testes de CLI rodavam o subprocesso com
  `env={"NOMOS_HOME": …, "PATH": ""}` — um ambiente mínimo que descartava
  `SystemRoot`. Sem ele, o Python filho morria no arranque com
  `_Py_HashRandomization_Init: failed to get random numbers`. Todos os
  demais erros (StopIteration, IndexError, JSONDecodeError, assert 1==0…)
  eram consequência: subprocesso morto ⇒ stdout vazio.
- **`tests/_cli_env.py`**: helper único que monta o env dos subprocessos —
  mantém a intenção (PATH vazio, para provar que o CLI não depende do PATH)
  e preserva SÓ o essencial do SO (SystemRoot etc.). No POSIX o resultado é
  idêntico ao dict antigo (zero mudança); no Windows o filho passa a bootar.
  14 call sites migrados em 13 arquivos.
- **`test_arbitragem`**: `cwd` era calculado com `str(...).rsplit("/src/")`
  — no Windows o path usa `\`, o split não cortava e o `cwd` virava um
  arquivo `.py` (`NotADirectoryError: WinError 267`). Agora
  `Path(...).parents[3]` (portável).
- **`ci.yml`**: Windows VOLTOU à matriz completa de testes (3 SO × 4
  Pythons). O E2E de e-mail (socket cru, frágil) segue Linux-only via
  skipif; o resto agora roda no Windows.

### Fixed (MC46.2 — CI verde: Windows = smoke do produto)
- **CI vermelho no `main` diagnosticado**: as anotações do GitHub Actions
  mostraram que a falha era SÓ nos jobs de teste do `windows-latest` (todas
  as versões de Python) — Ubuntu, macOS e o **smoke do produto no próprio
  Windows** passavam. Ou seja: o produto está limpo no Windows; o que
  falhava eram testes de integração POSIX (sockets, subprocessos, servidores
  locais dos conectores/painel), sem refletir bug de produto.
- **`ci.yml`**: a suíte completa roda em Linux + macOS (4 Pythons cada);
  o Windows fica coberto pelo job `smoke` (build do wheel + `nomos doutor`,
  que já passava). CI honesto: nada mascarado, produto verificado nos 3 SO.
- **Cross-platform real**: `conectores_exemplo()` devolvia o caminho do
  manifesto com `str(Path)` — no Windows sairia com `\`, quebrando o
  comando que o usuário copia. Agora `as_posix()` (barra normal em todo SO);
  teste trava o contrato.

### Added (MC46.1 — cobertura: os conectores na vitrine e no manual)
- **Site § Conexões ("Seu briefing onde você já está")**: seção nova de
  marketing com os 3 canais (Telegram/WhatsApp/e-mail), a receita honesta
  (`nomos mcp exemplos` → confiar → rotina → agendar) e a nota franca
  sobre Instagram/TikTok. Nav e card de recursos apontam para ela;
  roadmap do site atualizado (parou no MC32 → agora reflete MC34–MC46).
- **README**: tabela de comandos ganhou `nomos painel`, `nomos mcp
  exemplos` e a rotina `briefing-telegram:<chat>`; a doc
  `CONECTORES_SOCIAIS.md` — que estava **órfã** — agora é linkada no
  README e no site.
- **`docs/CONECTORES_SOCIAIS.md`**: linha do e-mail (SMTP) incluída.
- Testes: `tests/test_cobertura_docs.py` (6) travam a cobertura — site
  mostra os 3 canais + receita, README documenta, doc não volta a ser
  órfã, roadmap reflete as fases. Validação visual real (0 erros de
  console). Suíte completa: 1423 passed.

### Added (MC46 — terceiro canal: briefing por e-mail via SMTP)
- **Conector `examples/mcp/email-smtp/`**: servidor MCP local em stdlib
  pura (`smtplib`) — `email_quem_sou` (valida sem enviar) e `email_enviar`.
  Credenciais SÓ por ambiente (`NOMOS_SMTP_HOST/PORT/USER/PASSWORD/FROM`);
  STARTTLS por padrão e **recusa texto claro** salvo `NOMOS_SMTP_INSECURE=1`
  (opt-in local); senha redigida de qualquer erro; sem config, falha
  fechado. Toda tool **A3** (credencial + rede) ⇒ gate a cada chamada.
- **Canal `briefing-email:<endereço>`**: a extensibilidade do MC45 rendeu —
  bastou uma entrada em `_CANAIS` (assunto "Briefing NOMOS — <data>").
  `validar/prever` honestos; o Dash e `nomos mcp exemplos` já mostram o
  conector automaticamente (fonte de verdade única do MC45.1).
- `docs/CONECTORES_SOCIAIS.md` atualizado (linha do e-mail).
- Testes: `tests/test_mcp_email.py` (9 — dialeto stdio real, fail-closed,
  smtplib mockado, recusa de texto claro, senha jamais vaza, manifesto/
  trust store, aparece em conectores_exemplo, e **E2E sem internet** com
  um servidor SMTP FAKE em socket local recebendo o briefing real após o
  gate aprovar). Suíte completa: 1417 passed.

### Added (MC45 — briefing no WhatsApp: paridade de canais)
- **Ação de rotina `briefing-whatsapp:<numero>`**: simétrica ao
  `briefing-telegram`, entrega o briefing do dia pela WhatsApp Cloud API
  oficial — mesmo caminho governado (trust store → gate A3 → conector),
  mesma verdade (`prever_acao` explica; sem aprovação, não sai; auditado).
  Número validado (internacional, só dígitos); manifesto por
  `NOMOS_WHATSAPP_MANIFESTO`.
- **Refactor para uma fonte de verdade**: `enviar_briefing` virou um
  atalho de `entregar_briefing(ctx, canal, destino, …)` com um mapa de
  canais (`_CANAIS`) — Telegram e WhatsApp compartilham 100% do fluxo,
  só mudam a tool do conector e como o destino é embalado. Compat total:
  `enviar_briefing(...)` e todos os testes MC41/MC42 seguem verdes.
- Testes: `tests/test_briefing_whatsapp.py` (7 — validação/preview,
  fail-closed sem confiança, gate negado, **E2E sem internet** com Cloud
  API fake local recebendo o briefing real após aprovação, anti-regressão
  do Telegram, canal desconhecido recusado). Suíte completa: 1408 passed.

### Added (MC44 — descoberta dos conectores pelo terminal)
- **`nomos mcp exemplos`**: lista os conectores que acompanham o NOMOS
  (Telegram, WhatsApp…) com o estado real de confiança (● ligado /
  ○ disponível / ✗ revogado), o nível de risco e o comando exato para
  ligar cada um — o equivalente terminal do widget "conexões" do Dash.
  `--json` para scripts. Honesto quando a pasta `examples/` não está
  presente (ex.: wheel instalado): explica em vez de apontar para o vazio.
- **`mcp_catalogo.conectores_exemplo(home, raiz=None)`**: helper com uma
  fonte de verdade — resolve `examples/mcp` a partir do cwd/projeto,
  cruza cada manifesto com o trust store, ignora manifesto torto
  (fail-closed). Raiz explícita é soberana (sem fallback).
- Testes: `tests/test_mcp_exemplos.py` (6 — lista do repo, status reflete
  o trust store, pasta ausente ⇒ vazio, manifesto torto ignorado, CLI
  texto+JSON, parser). Suíte completa: 1401 passed.

### Added (MC42 — briefing-telegram vira AÇÃO DE ROTINA)
- **Nova ação `briefing-telegram:<chat_id>`** no vocabulário de rotinas
  (`nomos rotinas criar "Briefing TG" 08:00 briefing-telegram:424242`):
  o agendador de 15 min passa a entregar o briefing sozinho — com
  aprovação humana SEMPRE (`rotinas executar --panel` usa a fila do
  painel; sem aprovador, A3 nega fechado e audita). `prever_acao` diz a
  verdade ("só sai com aprovação sua"); chat validado (número ou @canal;
  injeção recusada); manifesto por `NOMOS_TELEGRAM_MANIFESTO` (cron tem
  cwd/env mínimos). `executar_acao`/`executar_devidas` ganham `approver`
  opcional (compat total); linha base do agendador agora inclui
  `--panel` com o porquê no comentário.
- Teste-coroa: a automação COMPLETA — rotina criada → devida às 08:00 →
  `executar_devidas` com aprovador → briefing chega na Bot API fake local
  (zero internet), com `rotina.executada` + `rotina.briefing.entregue`
  na trilha. Suíte completa: 1395 passed.

### Added (MC41.1 — briefing agendado, com a verdade na frente)
- **`nomos rotinas briefing --panel`**: em uso agendado, a aprovação vem
  da fila do painel (just-in-time, TTL 5 min) — A3 nunca se auto-aprova;
  ninguém aprovou ⇒ não sai (fail-closed, auditado).
- **`nomos rotinas agendar --telegram <CHAT_ID>`**: além das linhas de
  sempre, imprime a linha PRONTA do cron para o briefing das 08:00
  entregue no Telegram — com os avisos honestos no próprio comentário
  (trocar SEU_TOKEN; aprovar no painel em até 5 min; senão não sai).
- **Dash Hub**: atalho copiável do briefing→Telegram (+ dica do agendar).
- Testes: contrato antigo do agendador intacto; linha nova com --panel,
  placeholder de token, TTL e fail-closed declarados; parser; atalho no
  Dash. Suíte completa: 1390 passed.

### Added (MC41 — a primeira automação de ponta a ponta: briefing → Telegram)
- **`nomos rotinas briefing --telegram <CHAT_ID>`**: o briefing do dia
  (gerado 100% localmente) ENTREGUE pelo conector MCP confiado — juntando
  as peças que já existiam: rotinas + trust store + política/gate +
  ClienteMCP + conector Telegram. Sem confiança registrada ⇒ instrui e
  para; gate negado ⇒ nada sai (e fica auditado:
  `rotina.briefing.entrega_negada`); entregue ⇒ `rotina.briefing.entregue`.
  `--manifesto` aceita outro conector com a mesma tool.
- Teste-coroa em `tests/test_briefing_telegram.py`: ponta a ponta SEM
  internet — Bot API fake em 127.0.0.1 recebe o briefing real enviado
  pelo conector real (processo stdio) depois do gate aprovar; mais os
  casos fail-closed (sem confiança; gate negado ⇒ conector nem conecta).
  Suíte completa: 1386 passed.

### Added (MC40 — conexões: redes sociais via MCP + Dash Hub)
- **Conector Telegram (`examples/mcp/telegram/`)**: servidor MCP local em
  stdlib pura sobre a Bot API OFICIAL — `telegram_quem_sou`,
  `telegram_enviar`, `telegram_atualizacoes`. Token SÓ por ambiente
  (`NOMOS_TELEGRAM_TOKEN`), jamais em arquivo; sem token, falha fechado
  com instrução; token redigido de qualquer erro (testado). Todas as
  tools **A3** (credencial+rede) ⇒ gate de aprovação a cada chamada.
- **Conector WhatsApp Cloud (`examples/mcp/whatsapp-cloud/`)**: envio de
  texto e templates pela Business Cloud API OFICIAL da Meta (credenciais
  por ambiente; receber exige webhook público — dito na cara, não
  escondido). Mesmas garantias e nível A3.
- **`docs/CONECTORES_SOCIAIS.md`**: o mapa honesto dos 4 canais —
  Telegram pronto, WhatsApp envio pronto, Instagram/TikTok mapeados com
  requisitos reais (apps aprovados) e o porquê de NÃO usarmos bibliotecas
  não-oficiais (violam termos, derrubam contas).
- **Dash Hub**: o Dash virou hub do dia a dia — widget **conexões** (o
  que está ligado ● e o que dá para ligar ○, direto do trust store, com
  o comando exato; ligar continua passando pelo gate no terminal) e
  **atalhos copiáveis** (organizar pasta com desfazer, rotinas, backup,
  ligar o Telegram). Nova seção `conexoes` em `dados_dashboard`/API.
- Testes: `test_mcp_telegram.py` (10 — dialeto stdio em processo real,
  fail-closed, API mockada, redação de token, manifesto/trust store,
  integração com o ClienteMCP do NOMOS) + `test_mcp_whatsapp.py` (5) +
  Dash Hub (2). E2E: conexões ao vivo no navegador (telegram ● /
  whatsapp ○), 4 atalhos copiáveis, zero erros de console. Suíte: 1382.

### Added (MC39.1 — Dash: mais profundidade, mesma calma)
- **Sparkline com faixa 24h ↔ 7d**: nova série real `atividade_7d`
  (eventos/dia, mesma passada única na trilha); alternância no próprio
  widget, sem métrica extra na tela (glanceability preservada).
- **Placar de decisões (24h)** no tile de aprovações: ✓ aprovadas ·
  ✗ negadas · ⏱ expiradas — contado dos metadados da fila (o campo token
  jamais é lido; teste garante que não vaza na API).
- **`mem_pico_mb` no health/** (RSS de pico do processo, stdlib puro,
  normalizado Linux/macOS) — visível no rodapé do Dash.
- E2E real: alternância 24↔7 barras no navegador, placar "✓1 · ✗1 · ⏱0"
  com decisões reais, zero erros de console. Suíte completa: 1365 passed.

### Added (MC39 — NOMOS Dash: a ferramenta própria de mission control)
- **`dash/` no painel**: dashboard AO VIVO, uma tela, leitura pura (sem
  nenhum POST). Referências aplicadas (mission-control/glanceability,
  btop): 4 sinais vitais num relance (status, aprovações, memórias a
  revisar, cadeia), **sparkline 24h da atividade REAL** (nova série
  `atividade_24h`: 24 buckets/hora computados da trilha, só timestamps),
  motores por modalidade, avisos e uptime. Polling same-origin: `health/`
  5s, seções 30s; realce suave SÓ quando um valor muda (sem flicker-
  ansiedade; respeita `prefers-reduced-motion`); pausa sozinho com a aba
  oculta + botão pausar; queda de conexão mostra "reconectando…" — nunca
  inventa dado. Shell 100% estático (dados via JSON + `textContent`,
  XSS-safe por projeto); forma canônica `dash/` (301 sem barra); link
  "dash ao vivo ↗" na sidebar.
- **CSP** ganhou `connect-src 'self'` (fetch SÓ da própria origem — o
  resto segue `default-src 'none'`). **`health/`** ganhou `uptime_s` e
  `uptime_hum`.
- **Site**: fotos regeneradas do produto ATUAL (abas MC37 + tema escuro,
  countdown vivo) + figure destacada do Dash com copy honesto; alt/captions
  atualizados (nada de "lateral" que não existe mais).
- Testes: `tests/test_painel_dash.py` (8 casos — shell estático sem
  interpolação, widgets, CSP, série 24h real via dados e API, uptime,
  405/404, link na sidebar). E2E real (Chromium + servidor vivo):
  aprovação criada com a página aberta fez o tile ir de 0→1 **sem
  reload**, sparkline com 24 barras, zero erros de console.

### Added (MC38 — chat local no painel, estilo ChatGPT)
Chat funcional embutido no painel, com histórico de conversas e conteúdo
visível, rodando **só motor local**. Testes: `tests/test_chat_painel.py` (7).
- **Aba "chat"** nova: histórico de conversas à esquerda (a "barra lateral" do
  ChatGPT), thread com bolhas usuário/agente à direita, composer embaixo. As
  conversas saem do ConversationStore real (o mesmo do `nomos chat`).
- **2ª porta de escrita governada** (`chat/enviar`): o painel deixa de ter
  "uma porta" e passa a ter duas — aprovações (token single-use) e chat. A
  porta do chat tem token CSRF por servidor, roda **apenas motor local**
  (respeita o cadeado; nuvem só no terminal, com opt-in), é **fail-closed**
  (sem motor pronto → grava uma nota honesta "instale o cérebro", jamais
  inventa resposta) e audita cada turno (`chat.painel.enviou/respondeu/
  sem_motor`).
- **Fail-closed por padrão**: no construtor do servidor o chat nasce
  DESLIGADO (o `render_html` puro segue sem `<form>`); `nomos painel` liga;
  `nomos painel --sem-chat` desliga.
- **Privacidade**: o conteúdo aparece (sua máquina, 127.0.0.1), passando por
  `redact_text` — chaves/tokens saem redigidos na exibição (testado).
- Conversas migraram da aba "cérebro" para a aba "chat" (âncora `#conversas`
  preservada). Site e cópia atualizados para "duas portas de escrita".

### Changed (MC37 — menos poluição visual, mais usabilidade)
Redesenho do painel para reduzir densidade, com tema claro/escuro. Testes:
`tests/test_painel_tema_e_abas.py` (6 casos) + contratos de layout atualizados.
- **Site: tema CLARO e ESCURO** (a pedido) com botão no cabeçalho
  (`aria-pressed`), respeito a `prefers-color-scheme`, persistência e boot no
  `<head>` (sem flash); paleta clara de contraste WCAG AA verificada.
- **Site: menos scroll** — hero de 6 → 4 números; os ~20 cards de recursos
  agora vivem em 3 grupos recolhíveis (`<details>`, o 1º aberto); a tabela de
  15 motores e a lista completa também recolhem; navegação do topo enxuta.
- **CLI**: `nomos --help` sem a chave gigante de comandos (metavar
  `<comando>`); epílogo aponta o menu amigável e o `--help` por comando.
- **Painel em 5 ABAS** (uma por vez) em vez de 16 seções empilhadas numa
  página só: `visão geral` · `cérebro` · `capacidades` · `operação` · `ajuda`.
  A visão geral abre por padrão; as demais trocam por clique. O rail lateral
  foi eliminado — o que ele mostrava (motor ao vivo, "precisa de você",
  atividade recente) migrou para a visão geral. KPIs 8 → 5.
- **Deep-links preservados**: cada aba traz uma subnav com as âncoras antigas
  (`#motores`, `#auditoria`…), e o JS ativa a aba que contém a âncora — links
  salvos e `#seção` continuam funcionando.
- **Recolhíveis**: catálogo completo de motores, tabela A0–A6 e últimos
  eventos da auditoria viraram `<details>` fechados por padrão — acesso a um
  clique, sem poluir.
- **Tema CLARO e ESCURO**: escuro segue padrão (brandbook congelado); há tema
  claro com paleta de contraste WCAG AA verificada, botão de alternância
  acessível (`aria-pressed`), respeito a `prefers-color-scheme` do sistema,
  persistência da escolha e boot antes do `<style>` (sem flash de tema).
- **Filtro** agora varre todas as abas (revela tudo enquanto há texto) e volta
  sozinho à aba ativa ao limpar.

### Added (MC34.2 — o painel na vitrine: fotos reais + marketing honesto)
- **Site § Painel ("Você vê tudo. Você decide tudo.")**: seção nova com
  screenshots REAIS do cockpit (capturados do código atual, retina, WebP
  otimizado — 3 imagens somando <300 KB), em moldura de navegador com
  legenda; cards de usabilidade (aprovar com token single-use, roteador ao
  vivo, busca/filtro) e a resposta REAL de `health/` exibida como terminal;
  CTA `nomos painel`. Nav ganhou "painel"; hero ganhou "Ver o painel por
  dentro"; card de recursos linka "Ver por dentro →".
- Testes: `tests/test_site_painel.py` (5 casos — imagens existem no repo,
  peso máximo por imagem e total, alt descritivo + lazy + dimensões
  declaradas (sem CLS), seção ligada na nav/hero, usabilidades reais
  citadas).

### Security (MC36 — revisão loop-100: concorrência e fail-closed)
Auditoria externa completa (código + UX + git) com correção total. Bloco 1 —
segurança e robustez, cada item com teste de regressão em
`tests/test_revisao_seguranca_2026.py`:
- **`nomos doutor` não executa mais código do diretório atual sem pedido**:
  o guardião do repositório (que roda `tools/*.py` do CWD) virou opt-in
  explícito `--repo` — antes, qualquer pasta com 3 arquivos certos ganhava
  execução ao rodar um comando anunciado como "só observa" (fail-open).
- **Aprovações são single-use DE VERDADE sob concorrência**: `decide()` agora
  reivindica a solicitação por `os.replace` atômico + lock — com N decisores
  simultâneos (duas abas do painel, painel + terminal, duplo-clique), exatamente
  UM vence; claim órfão de um crash expira fail-closed, jamais vira aprovação.
- **Cadeia de auditoria não bifurca com escritas concorrentes**: `append()`
  serializa por lock in-process (painel roda em ThreadingHTTPServer) +
  `fcntl.flock` best-effort entre processos; cauda parcial de um crash/disco
  cheio é REPARADA no próximo append (antes, o lixo ficava no meio do arquivo
  e `verify()` acusava violação para sempre).
- **Cadeado só-local**: alvo vazio/não-parseável (ex.: `"http://"`) deixou de
  classificar como loopback — não-parseável agora é remoto (fail-closed).
- **Redação da auditoria** cobre também os nomes de campo pt-BR `chave` e
  `credencial`.
- **Fila de aprovações não cai por arquivo corrompido**: entrada ilegível é
  pulada em `pending()` em vez de derrubar a listagem (painel incluso).
- **Painel valida o POST de decisão**: `Content-Length` não-numérico/negativo
  e corpo não-UTF-8 respondem 400 (antes: exceção na thread); erros do fluxo
  (400/405/409/413) agora respondem página mínima com link de volta ao painel
  em vez de texto cru sem saída.

### Changed (MC36 — revisão loop-100: usabilidade e coerência)
Bloco 2 — UX da CLI, do painel e fluxos simples:
- **Painel/terminal falam a língua de quem decide**: a categoria da aprovação
  aparece como rótulo humano ("A2 · sair para a rede") no card do painel, no
  painel antigo e em `nomos approvals list` — o id técnico continua visível.
- **Auto-recarregar do painel deixou de atrapalhar**: virou JS próprio,
  pausável — não recarrega enquanto você digita no filtro ou há aprovação na
  tela (o meta refresh antigo recarregava no meio da decisão); estado visível
  ("auto: Ns"/"pausado"); botões APROVAR/NEGAR desabilitam quando o pedido
  expira (clicar só renderia 409).
- **Painel**: contador acessível no filtro ("N de M itens", aria-live);
  marcador ↗ nos itens da sidebar que saem da página; botão "buscar" na
  auditoria; `scope="col"` nos cabeçalhos; tipografia mínima .72rem; borda do
  campo de busca com contraste ≥3:1; `// ` decorativo dos títulos legível.
- **Painel antigo (`approvals serve`)** herdou o hardening do 4.0: headers de
  segurança (CSP/nosniff/no-referrer/no-store), PRG 303 pós-decisão (F5 não
  reenvia mais a decisão) e 405 para POST em rota errada.
- **`nomos painel`**: `--somente-leitura` (nenhum POST aceito), `--sem-abrir`
  (a URL com segredo não passa pelo argv do abridor — visível em `ps`) e
  cache curto (2 s) da coleta para aguentar polling de `health/`; help do
  argparse não diz mais "somente leitura" (não era verdade no 4.0).
- **CLI 100% pt-BR na superfície de descoberta**: descrição do programa e
  `help=` nos 13 subcomandos que apareciam sem explicação (`init`, `agent`,
  `vault`, `consent`, `panic`, `run`, `skill`, `approvals`, `chat`, `memory`,
  `status`, `logs`).
- **Comandos pelados = default útil** (mesmo padrão de `nomos motores`):
  `nomos memoria` → candidatas · `nomos evidencia` → listar · `nomos mcp` →
  tools. O site ensina esses comandos sem subcomando; terminar em "uso: …"
  com erro era a UX quebrando a própria instrução.
- **Onboarding honesto**: com cofre já existente, o passo 4 avisa e NÃO pede
  senha (antes, qualquer senha digitada era ignorada e "confirmada"); sem
  motor local, o caminho recomendado agora começa pelo cérebro embutido
  (`nomos cerebro baixar`, ~400 MB, sem GPU) antes do Ollama.
- **Terminologia unificada**: "cofre" em todas as superfícies (site, doutor,
  chaves, onboarding, status) — eram 4 nomes para a mesma coisa.
- **`nomos chaves` não destrói mais a chave colada com senha errada**:
  `absorver_arquivo` valida a senha-mestra ANTES de ler/apagar o arquivo
  (novo `Vault.verify_passphrase`, com o mesmo lockout progressivo).
- **Rotinas**: a linha de crontab usa o caminho COMPLETO do Python entre
  aspas (com basename, cron de venv/pipx falhava em silêncio).
- **`comparar_versoes`**: metadado de build (`1.2.3+build`) não é mais
  tratado como pré-release.
- Coleta do painel: registry de agentes instanciado uma vez por coleta;
  conexão sqlite de conversas fechada em `finally`.

### Fixed (MC36 — revisão loop-100: o site diz a verdade)
Bloco 3 — site/index.html alinhado ao produto real (lema "nunca finge"):
- **Comandos publicados agora existem**: `nomos skill listar` → `nomos skills
  listar`; `nomos skill rodar busca-arquivos --pasta …` → `nomos skills rodar
  busca-arquivos --args '{"pasta": …}'` (a flag --pasta nunca existiu).
- **Versão honesta**: "Versão atual: v1.3.0rc4" virou "Última release
  publicada: pacote v1.3.0rc16 (pré-lançamento; o código na main já segue
  adiante)" — o wheel real da release É 1.3.0rc16 (verificado na API do
  GitHub); link direto para o `.whl` adicionado nos cards macOS/Linux e
  Windows (a instrução pedia 2 arquivos e o card só entregava 1).
- **Card do SDK sem promessa falsa**: `nomos agent create` não tem flags de
  objetivo/ferramentas/risco — o card agora descreve o fluxo real (create
  --name + manifesto no formato dos oficiais).
- **Números que fecham**: stat e tabela de motores agora refletem o catálogo
  real (15 entradas — adicionados servidor OpenAI-compatível, texto-como-
  código e skills); contagem de testes atualizada (1.330+).
- **Recursos agrupados**: os 20 cards planos viraram 3 blocos temáticos
  (cérebro & conversa · governança & segurança · operação & integrações) —
  hierarquia em vez de inventário.
- **Acessibilidade**: ~30 emojis decorativos com `aria-hidden="true"` (leitor
  de tela não anuncia mais "cadeado, mão levantada…" antes de cada card);
  `scope="col"` na tabela de motores.
- **Copy alinhada ao Painel 4.0**: card do painel não diz mais "Só leitura"
  ("ler é livre; a única ação é decidir aprovações, com token de uso único");
  "Caixa-forte e backup" → "Cofre e backup".
- **Marca**: `--fraco` sincronizado entre site e painel (#7c9a84, 6.3:1);
  tokens derivados documentados no brandbook como referência única.

### Added (MC34.1 — downloads no site + sinais reais)
- **Site § Baixar & instalar**: três caminhos claros — 🍎 macOS/Linux
  (`install.sh`), 🪟 Windows (`install.ps1`) e 🐙 pelo código (git clone +
  `pip install .`) — com botões apontando para os assets REAIS da release
  atual (tag verificada, SHA256 conferido no GitHub), versão visível,
  link "todas as versões" e instrução de verificação `SHA256SUMS`.
  Comentário de manutenção no HTML lembra de atualizar a tag a cada release.
- **`health/` virou sinal de verdade**: além de `ok/versao`, devolve
  `saudavel`, `status_geral`, `proximo_passo`, `avisos[]` (aprovações
  pendentes, memórias a revisar, cadeia de auditoria, evidências quebradas)
  e `motores_prontos` — pronto para rotinas, scripts e integrações locais.
- Testes novos: `tests/test_site_downloads.py` (8 casos — assets por tag,
  tag consistente entre instaladores, git visível, SHA256SUMS, nenhum
  link relativo quebrado, âncoras da nav íntegras) e cobertura dos avisos
  reais do health.

### Fixed (MC34.1)
- **9 links relativos quebrados no site** (`../docs/...`, `../README.md`)
  trocados por URLs absolutas do GitHub — funcionam de onde o site for
  servido (o site vive em `site/` e esses links 404avam fora do repo).
- **Último aviso do ruff no repo** (S110 em `mcp_client.py`): leitor daemon
  agora usa `contextlib.suppress` (idioma recomendado) — `ruff check .`
  100% limpo.

### Security & Fixed (MC35 — vistoria de ponta a ponta)
Vistoria completa do código com correções mínimas e anti-regressão (suíte 100%
verde após cada mudança). Destaques:
- **Cadeado local-first reforçado**: `OllamaProvider`/`OpenAICompatProvider`
  agora recusam host não-loopback na construção (`NOMOS_OLLAMA_HOST` remoto era
  aceito silenciosamente e a auditoria registrava `egress="nenhum"`); o catálogo
  de motores ignora host não-loopback do ambiente.
- **Conselho — quórum e integridade**: conselho sem juiz limpo (inclusive zero
  juízes) agora é fail-closed `INSUFFICIENT_JUDGES` (antes aprovava com confiança
  HIGH); estatísticas e vencedor calculados só sobre reviews limpas (autojulgamento
  não elege mais o vencedor); `session_id` real propagado aos envelopes de
  auditoria; provider/simulador plugável malformado não derruba mais `run()`.
- **Auditoria resiliente**: linha final parcial (crash no meio de um append) não
  trava mais toda a auditoria; `encoding="utf-8"` explícito preserva a cadeia de
  hash fora de UTF-8.
- **Redação de auditoria** passou a inspecionar listas/tuplas aninhadas (segredo
  dentro de lista era serializado sem redação).
- **Assinatura de skills**: manifesto assinado só com `entrypoint` instala
  corretamente (a reescrita para adicionar `entry` invalidava a assinatura
  legítima); chave privada ed25519 criada já com permissão `0600` (sem janela de
  exposição); execução de skill via argv (sem shell).
- **Servidores locais**: loop MCP resiste a JSON válido não-objeto (batch/escalar);
  painel exibe a contagem real de eventos (usava o índice de violação); redirect
  301 para a URL canônica; `panel` valida `Content-Length`.
- **Robustez**: memória tipada preservada no ciclo backup export→import; download
  de cérebro rejeita GGUF truncado; instalação do motor usa `sys.executable`;
  `/continuar` injeta o contexto retomado; `/conversas` não quebra mais o chat;
  FTS de conversas com trigger de DELETE (texto "esquecido" some do índice);
  escrita atômica e `encoding="utf-8"` em perfis, rotinas e consentimento;
  `signal.pause` com fallback no Windows.

### Added (MC34 — Painel 4.0: cockpit local)
- **Layout de aplicativo**: sidebar de navegação agrupada (agora/cérebro/
  capacidades/operação/ajuda) com badges de atenção, conteúdo central e rail
  de status à direita (motor ao vivo por modalidade, atenção, atividade);
  bloco Sistema no rodapé da sidebar (status, agente, modo, auditoria,
  relógio). Marca congelada intacta; responsivo (rail some, menu vira pills);
  acessível (skip-link, aria-label, focus-visible, prefers-reduced-motion).
- **Aprovações no painel (única porta de ação)**: a fila file-based de
  `kernel.approvals` agora aparece no painel com APROVAR/NEGAR — POST existe
  SÓ em `aprovacoes/decidir`, transportando o token single-use da própria
  solicitação (TTL 5 min, comparação constante, tudo auditado; PRG 303).
  Qualquer outro POST segue 405; `fila_aprovacoes=False` volta ao modo 100%
  somente leitura. Token jamais aparece em `api/`/JSON.
- **`health/`**: sinal de vida em JSON (ok, versão, só-local, pendências)
  para scripts e monitoramento.
- **`api/?secao=<chave>`**: recorte de uma seção só; desconhecida ⇒ 404 com
  a lista de disponíveis.
- **`audit/?q=`**: busca server-side na trilha (metadados redigidos), sempre
  escapada (anti-XSS testado), com contagem e limpar-filtro.
- **Dados novos no painel**: `sistema` (python/plataforma/home/bancos),
  `roteador_vivo` (decisão explicada por modalidade) e `aprovacoes`
  (contagem). Seções novas: Sistema e Ajuda rápida (comandos + leis da casa).
- **Headers de segurança** em toda resposta: CSP restritiva (default-src
  'none'), nosniff, no-referrer, no-store.
- **JS próprio inline** (zero terceiros, zero rede): scrollspy na sidebar,
  filtro rápido de cards/tabelas, contagem regressiva das aprovações e
  relógio. Página degrada 100% sem JS.
- Testes: `tests/test_painel_v4_hermes.py` (15 casos — layout, health,
  api?secao, busca+XSS, aprovar/negar/token errado/reuso/405/sem fila,
  headers, vazamento de token). Os contratos MC29/MC33/v017 passam SEM
  alteração.

### Added (MC33 — regra: site sempre reflete o produto)
- **Gate `brand:site_atualizado`** no update agent (MC33.0): introspecta os
  comandos top-level do CLI e exige que cada capacidade voltada ao usuário
  apareça no `site/index.html`. Comando novo sem menção no site ⇒ build
  vermelho no CI. Internos/infra ficam em `SITE_COMANDOS_INTERNOS` (decisão
  consciente, testada contra exclusões órfãs).
- **Site atualizado** para MC30–MC32: cards de missões (executor), MCP
  (servidor + cliente), conversa em streaming/`/arbitrar`, memória revisável,
  backup, fila de aprovações e atualização com licença; roadmap e stats
  (1.280+ testes) em dia. Marca congelada intacta.


### Added (MC32 — execução: ruídos + M1)
- **Missão `renomear` (P2)**: diff-prévia em lote (antes → depois no plano),
  colisão-safe, mesma trilha aprovação/evidência/desfazer do executor.
- **Executor de missões (P1)**: `nomos missao planejar/executar organizar
  <pasta>` — plano legível dry-run por padrão; execução exige gate A1 +
  confirmação digitada; evidência verificável com manifesto de DESFAZER;
  `nomos missao desfazer` reverte (também gateado). Nunca sobrescreve.
- **Trust store de MCPs (M2)**: `nomos mcp confiar/revogar/catalogo` —
  confiança por impressão (SHA-256 do manifesto); conectar/chamar só rodam
  server confiável (experimental exige "ACEITO O RISCO"; revogado bloqueia;
  manifesto alterado volta a experimental).
- **MCP client (M1)**: `nomos mcp conectar/chamar <manifesto.json>` — servers
  MCP locais viram capacidades externas com nível A0–A6 por tool (desconhecida
  herda A5 fail-closed); A0 direto, A1+ só com aprovação interativa (negação
  auditada sem executar). Nunca auto-instala; dogfood contra o próprio server.
- **Higiene**: artefatos regeneráveis git-ignorados removidos do repo; pacote
  histórico v0.10 do invólucro movido para `NOMOS_REPO/archive/`.

### Added (MC32 — planejamento)
- `docs/ROADMAP_4.md`: plano de potência real — trilha P (executor de missões
  aprovável, skills A1 com diff-prévia, visão de tela via OmniParser V2 local
  em 3 fases gateadas por A4), trilha M (MCP client com manifesto de risco,
  trust store, server v2 com Tasks, HTTP loopback), trilha I (OmniParser,
  faster-whisper, embeddings locais, OCR, docling, SearXNG opt-in, VLMs) e
  trilha Q (bancada de motores, harness via arbitragem). 12 missões
  priorizadas; fatos externos pesquisados e citados (licenças AGPL/MIT do
  OmniParser exigem processo separado; MCP estável 2025-11-25, RC 2026-07-28).

### Added (MC31 — B1 provado e completado)
- **NOMOS como servidor MCP (C1)**: `nomos mcp servir` — Model Context
  Protocol sobre stdio (sem rede), 5 tools somente leitura (status,
  capacidades, evidências, memória redigida, roteador explicado); erros
  fail-closed e auditoria por tool call. `nomos mcp tools` lista.
- **Memória 2.0 (B5)**: `nomos memoria candidatas [--json]` e `nomos memoria
  revisar` (interativo; sem TTY nega fail-closed e a fila fica intacta);
  painel mostra a fila pendente.
- **`/arbitrar` no chat (B2)**: arbitragem real multi-motor na conversa,
  só motores locais (nuvem permanece exclusiva da CLI gateada); honesto
  sem motor pronto; aviso de divergência alta.
- **Chat com motor OpenAI-compatível**: cadeia local-first do chat vira
  embutido → Ollama → LM Studio/llama.cpp (normal e streaming SSE), com
  auditoria própria. `NOMOS_OPENAI_COMPAT_BASE` para porta customizada.
- **Contratos de conversa blindados**: 1º token antes do fim, fallback sem
  stream, degradação honesta, RAG de memórias no contexto — o streaming e a
  memória-no-contexto da v1.1 agora têm testes de contrato dedicados.

### Added (MC30 — fecho da onda A + B7 + C3)
- **Doutor unificado (A3)**: dentro de um repo do NOMOS, `nomos doutor` inclui
  os agentes guardiões (docs & marca, git) como seções do check-up.
- **Erros E011/E012 (A6)**: evidência violada e nuvem-não-plugada ganham
  código pesquisável, frase humana e próximo passo (docs/ERROS.md).
- **Rotinas exportáveis (B7)**: `nomos rotinas exportar` gera launchd plist,
  systemd timer+service ou .cmd do Agendador do Windows — o NOMOS nunca
  instala sozinho.
- **Motor OpenAI-compatível (C3)**: LM Studio/llama.cpp server/LocalAI no
  catálogo como motor local (probe 127.0.0.1:1234) + `OpenAICompatProvider`
  loopback-por-lei (host externo recusado na construção).

### Added (MC30 — onda A + Painel 2.0)
- **Painel 2.0**: rotas read-only `/api` (dashboard em JSON, sem vazamento de
  segredo — testado), `/audit` (verificação real da cadeia de hash + últimos
  eventos) e `/roteador` (decisão explicada por modalidade); catálogo completo
  de motores, seção Capacidades, auto-refresh opt-in `?refresh=N` e link para
  abrir o relatório de cada evidência. Loopback/segredo/405 preservados.
- **Update agent (A1)**: `--diff` propõe correção específica para cada check
  `brand:*` reprovado (deriva_de_marca, proposal-only).
- **Evidências (A2)**: `nomos evidencia listar [--json]` com verificação de
  integridade por pacote.
- **CI (A5)**: gate de cobertura dirigido (kernel/evidencia e
  ext/skill_catalogo ≥90%).

### Added
- `docs/ROADMAP_3.md` (MC30): plano de aprimoramentos, funcionalidades e
  conexões pós-rc17 — ondas A (aprimorar), B (produto), C (conexões gateadas:
  MCP server/client, motores OpenAI-compatíveis, Telegram, e-mail, CalDAV,
  pasta viva, webhooks loopback) e D (PyPI nome próprio, brew/winget,
  atualização assinada, SBOM, marketplace de skills), com top-10 priorizado
  e anti-metas.

## [1.3.0rc17] — 2026-07-05 (Motor Council MC10–MC27 + site + arbitragem real + MC29 governança/agentes/evidências: contrato único de flags proibidas, site com brandbook congelado e update agent read-only)

### Added (MC29 — plano profissional: 7 implementações)
- **Política formal de segurança** (`docs/governance/SECURITY_POLICY.md`):
  invariantes SEC-01…SEC-12 (escada A0–A6, fail-closed, cadeado, segredos)
  como contrato executável — testes provam cada uma e a sincronia doc↔testes.
- **Brand + Site Sync Agent (MC29.0)**: update agent vira guardião da marca —
  checks `brand:paleta`, `brand:tagline`, `brand:instalacao_oficial` e
  `brand:versao_coerente` no gate de CI.
- **Sistema de evidências** (`kernel/evidencia.py` + `nomos evidencia
  criar/verificar`): pacote auditável por missão (relatório, manifesto,
  SHA256SUMS), redigido (segredos nunca tocam o disco) e verificável offline.
- **Git Agent seguro** (`tools/nomos_git_agent.py`): --check/--suggest/
  --handoff; git só por allowlist de LEITURA; sem --push/--commit por
  contrato — push é sempre decisão humana.
- **Roteador explicável** (`engine_router.relatorio_decisao` + `nomos motores
  recomendar <mod> --json`): decisão + trace com todos os candidatos, motivos
  e regras aplicadas; contrato de `rotear()` inalterado.
- **Catálogo de capacidades** (`ext/skill_catalogo.py` + `nomos skills
  catalogo [--json]`): 8 campos por skill (nome, descrição, entrada, saída,
  risco, status, permissões, exemplos), risco sempre visível.
- **Painel web**: seções novas de Evidências de missões (verificação real de
  integridade) e Política de permissões A0–A6 viva; segue loopback-only e
  somente leitura.

### Added (ARBITRAGEM + MC-VALIDACAO-E2E)
- **Arbitragem real entre motores** (`cognition/arbitragem.py` + CLI
  `nomos motores arbitrar "<pergunta>"`): motores prontos geram candidatos
  reais, juízes cegos pontuam, árbitro converge na melhor execução; fail-closed
  e honesto (sem motor pronto ⇒ bloqueia e explica; `final_content` sempre de
  candidato real). Local-first; nuvem só com opt-in. 16 testes novos.
- **Site expandido**: recursos, motores & integrações, agentes, skills e escada
  de risco A0–A6 na landing (missão SITE_EXPAND, brandbook congelado preservado).
- `tests/test_missao_validacao_anti_regressao.py`: 6 contratos — trava de
  execução real do council, integridade (SHA-256) do brandbook congelado, docs
  essenciais presentes, cobertura do `.gitignore`, proibição de `pip install
  nomos` puro nos docs oficiais, coerência de versão pyproject ↔ pacote.

### Fixed (MC-VALIDACAO-E2E)
- **Docs e site não recomendam mais `pip install nomos` puro** — o nome `nomos`
  no PyPI pertence a projeto de terceiros (dowhiledev, "multi-step agent
  framework"); seguir o manual antigo instalaria outro software. Instalação
  oficial passa a ser via GitHub/instaladores, com aviso explícito (README,
  manual de instalação, brandbook §5, site, `docs/INSTALL.md`).
- README: contagem de testes desatualizada ("884" → "mais de 1.100").
- `pyproject.toml`: URL do Changelog corrigida (`blob/main/CHANGELOG.md`;
  a anterior apontava para `nomos/CHANGELOG.md`, caminho inexistente no repo).
- `docs/INSTALL.md`: exemplo de wheel com versão fixa 0.12.0 → placeholder.

### Added (MC25–MC27)
- **Site NOMOS** (`site/`): landing estática com brandbook congelado
  (`docs/brand/`), página 404, assets e `preview.py`; guia de instalação em
  `docs/installation/` (MC25; polish/rebrand em `docs/missions/SITE_*`).
- **NOMOS Update Agent** (`tools/nomos_update_agent.py`, MC27.0): agente
  **read-only/proposal-only** de consistência de documentação. `--check
  [--json]` funciona como gate de CI (exit 0/1, campos estáveis,
  `real_execution_enabled=false`, `auto_push_enabled=false`); `--diff [--json]`
  propõe patches sem escrever (`PROPOSTA_DIFF_ONLY`, `NO_WRITE`,
  `HUMAN_APPROVAL_REQUIRED`); `--apply` permanece bloqueado fail-closed.
  Contrato em `docs/governance/NOMOS_UPDATE_AGENT.md`. 75 testes novos
  (MC25 deliverables + MC26 check + MC27 diff). Suíte: 1024 → 1114.
- **Higiene de repo**: `.gitignore` ignora diretórios de extração de
  sdist/build (`/nomos-[0-9]*/`) e `.DS_Store`; `conftest.py` raiz evita
  "import file mismatch" na coleta do pytest.

### Changed (MC24)
- Reconciled the Motor Council dry-run **forbidden flags** contract between CLI
  and chat (decisão **A** — unificar): as duas superfícies passam a consumir o
  **mesmo** conjunto de 10 flags de uma fonte única testável,
  `src/nomos/council/forbidden_flags.py` (`FORBIDDEN_FLAGS` +
  `is_forbidden_flag`/`find_forbidden`). A CLI, que listava 8, passou a 10
  (`--vault-real`/`--engine-real` deixam de ser tratadas como *desconhecidas* e
  passam a ser *proibidas*, como no chat); `cli_dry_run.py` e `chat_dry_run.py`
  agora referenciam o **mesmo objeto** do contrato, eliminando a divergência
  herdada (documentada em MC20/MC22/MC23). Comportamento observável para o
  usuário: recusa fail-closed idêntica (mensagem, exit code, sem eco) nas duas
  superfícies para as 10 flags.

### Security (MC24)
- Detecção por **igualdade estrita** (nunca prefixo/substring): flags parecidas
  mas legítimas (`--realmente`, `--enabled`, `--cloudy`) não geram falso
  positivo; seguem recusadas como *desconhecidas* pelo parser. O dry-run segue
  fail-closed; o prompt e a flag nunca são ecoados; a mensagem humana não usa
  jargão; o JSON técnico preserva a estrutura segura. 72 testes novos
  (contrato + paridade CLI/chat + comportamento + pureza AST + guarda
  anti-divergência que impede hardcodar a lista fora da fonte única). Suíte:
  952 → 1024.

### Not changed (MC24)
- `safe_output.py` **não** foi alterado (o contrato de flags é ortogonal à saída
  segura); nenhuma execução real habilitada; `.github/` e `pyproject.toml`
  intocados; nenhuma tag, release ou publicação PyPI.

### Changed (MC23)
- Migrated the Motor Council chat dry-run output to the shared safe output
  helper: `/conselho simular` agora usa `build_safe_output` +
  `render_json_output` (`src/nomos/council/safe_output.py`) como fonte da
  estrutura segura e do JSON, em vez de montar o JSON à mão. O `--json` do chat
  passou de 8 para 10 campos (adição compatível de `interface`/`mode`),
  alinhando com o CLI (MC22).
- Improved chat dry-run human messages for non-technical users: resposta mais
  simples e amigável ("Simulação segura concluída. Nada foi executado de
  verdade. Nada foi salvo. Nenhum dado sensível foi exibido."), sem jargão; o
  bloco técnico `DRY_RUN=true`/`REAL_*` fica sob "Status:" e os detalhes
  completos no `--json`.

### Security (MC23)
- Chat dry-run output remains redacted and emits only approved safe scalar
  fields: o prompt nunca é ecoado, o resultado do orquestrador nunca é
  serializado (sem `to_dict`/`repr`/`vars`/`asdict`), mensagens não-`/conselho`
  seguem retornando `None` e o harness/policy/vault/audit reais não são
  chamados. 15 testes novos (migração + UX + regressão). Suíte: 937 → 952.

### Not changed (MC23)
- CLI dry-run was not changed in this phase (`cli_dry_run.py`/`cli.py` intocados)
  e o helper `safe_output.py` não foi alterado.
- No real engine execution enabled.
- No PyPI publication; nenhuma tag ou release criada.

### Changed (MC22)
- Migrated the Motor Council CLI dry-run output to the shared safe output
  helper: `nomos conselho simular` agora usa `build_safe_output` +
  `render_json_output` (`src/nomos/council/safe_output.py`) como fonte da
  estrutura segura e do JSON, em vez de montar o JSON à mão. O `--json` do CLI
  passou de 8 para 10 campos (adição compatível de `interface`/`mode`).
- Improved CLI dry-run human messages for non-technical users: saída mais
  simples e amigável ("Simulação segura concluída. Nada foi executado de
  verdade. Nada foi salvo. Nenhum dado sensível foi exibido."), sem jargão; o
  bloco técnico `DRY_RUN=true`/`REAL_*` fica sob "Status:" e os detalhes
  completos no `--json`.

### Security (MC22)
- CLI dry-run output remains redacted and emits only approved safe scalar
  fields: o prompt nunca é ecoado, o resultado do orquestrador nunca é
  serializado (sem `to_dict`/`repr`/`vars`/`asdict`), `conselho` continua
  roteado antes de `_paths()` e o harness/policy/vault/audit reais não são
  chamados. 15 testes novos (migração + UX + regressão). Suíte: 922 → 937.

### Not changed (MC22)
- Chat dry-run was not migrated yet (`chat_dry_run.py`/`amigavel.py`
  intocados); o helper `safe_output.py` não foi alterado.
- No real engine execution enabled.
- No PyPI publication; nenhuma tag ou release criada.

### Added (MC21)
- Added isolated Motor Council shared safe output/redaction helper
  (`src/nomos/council/safe_output.py`) for future CLI/chat dry-run
  unification: `CouncilSafeOutput` (frozen dataclass, 10 campos escalares
  seguros + `to_json_dict`) e as funções `build_safe_output`/
  `render_human_output`/`render_json_output`/`render_denied_output`/
  `render_gate_blocked_output`/`render_exception_output`, parametrizadas por
  `interface` (`cli`/`chat`).

### Security (MC21)
- Safe output helper emits only approved scalar fields and fails closed for
  invalid results: nunca serializa o resultado inteiro do orquestrador (sem
  `to_dict`/`repr`/`vars`/`asdict`), nunca emite prompt/content/engine_id/
  secret/token/api_key/trace/audit_envelope, e trava
  `dry_run=true`/`would_execute=false`/`would_write_audit=false` por
  construção. `interface`/`mode` inválidos ⇒ `ValueError`; resultado inválido
  ⇒ `SAFE_OUTPUT_INVALID_RESULT`. 36 testes novos (incl. AST). Suíte: 886 → 922.

### Not changed (MC21)
- CLI and chat dry-run commands were not migrated yet (`cli_dry_run.py`/
  `chat_dry_run.py`/`cli.py`/`amigavel.py` intocados).
- No real engine execution enabled; no runtime behavior changed.
- No PyPI publication; nenhuma tag ou release criada.

### Documentation (MC20)
- Added Motor Council shared output/redaction helper specification for future
  CLI/chat dry-run unification
  (`docs/architecture/MOTOR_COUNCIL_SHARED_OUTPUT_REDACTION_SPEC_v1.md`, 20
  seções): documenta a duplicação controlada entre `cli_dry_run.py` e
  `chat_dry_run.py` (incl. o achado de que a CLI tem 8 flags proibidas e o
  chat 10), os invariantes de segurança compartilhados, os dados proibidos e
  campos escalares permitidos, os contratos de saída por `interface`, um
  esboço de API (`CouncilSafeOutput` + `build_/render_*`, `API_SKETCH_ONLY`),
  o plano de migração MC21–MC24 e o plano de testes futuros. Ponteiros
  adicionados em INDEX, UX spec e chat dry-run spec.

### Not changed (MC20)
- No runtime behavior changed; nenhum helper implementado.
- No CLI/chat refactor performed (`cli_dry_run.py`/`chat_dry_run.py`
  intocados); suíte permanece em 886.
- No real engine execution enabled.
- No PyPI publication; nenhuma tag ou release criada.

### Documentation (MC19)
- Aligned README and Motor Council UX documentation with CLI **and** chat
  dry-run availability: README `## Motor Council` reescrita (ambas as
  superfícies têm `simular` em dry-run; o resto segue desabilitado), contagem
  de testes corrigida (778 → 884). `MOTOR_COUNCIL_INDEX_v1.md` ganhou o bloco
  "Estado de UX/superfícies" (MC14–MC18, `CLI_DRY_RUN_AVAILABLE=true`,
  `CHAT_DRY_RUN_AVAILABLE=true`, `REAL_EXECUTION_AVAILABLE=false`,
  `PRODUCTION_READY=false`) e nota sobre a duplicação controlada CLI/Chat.
  `MOTOR_COUNCIL_UX_SPEC_v1.md` ganhou "Current implementation status";
  `MOTOR_COUNCIL_CHAT_DRY_RUN_SPEC_v1.md` marcado como `IMPLEMENTATION=MC18_DONE`.

### Changed (MC19)
- Clarified Motor Council CLI/chat help text to reference the dry-run
  simulation commands: a linha do `/ajuda` do chat agora aponta para
  `/conselho simular` (dry-run), e um comentário interno desatualizado do
  `cli.py` foi corrigido. Nenhuma lógica de roteamento mudou; guardas de help
  adicionadas por teste.

### Not changed (MC19)
- No runtime behavior changed (`cli_dry_run.py`/`chat_dry_run.py`/orchestrator/
  harness/policy_gate/audit_envelope intocados).
- No real engine execution enabled; no CLI/Chat refactor.
- No PyPI publication; nenhuma tag ou release criada.

### Added (MC18-UX)
- Added `/conselho simular <texto>` as a redacted dry-run chat command backed
  by the Motor Council dry-run orchestrator (`CouncilOrchestratorDryRun`).
  Flags: `--modo rapido|balanceado|critico|paranoico` (paranoico ⇒ privado),
  `--privado`, `--json`, `--iniciante`, `--avancado`. Saída humana
  (`[NOMOS-MC-CHAT-DRY-RUN]`/`[NOMOS-MC-CHAT-GATE-BLOCKED]`) e JSON mínimo
  escalar. Novo módulo `src/nomos/council/chat_dry_run.py`; o ramo `/conselho`
  do loop de `amigavel.py` passou a rotear só `simular` para dry-run, mantendo
  os demais subcomandos desabilitados.

### Security (MC18-UX)
- Motor Council chat dry-run performs no real engine execution, persistence,
  real policy, real audit or real vault calls: `simular` chama apenas o
  orquestrador dry-run, nunca o harness real, e nunca constrói contexto de
  kernel. O prompt nunca é ecoado (humano/JSON/erro); flags proibidas
  (`--real`/`--enable`/`--cloud`/…) e desconhecidas falham fechado
  (`[NOMOS-MC-CHAT-DENIED]`). A saída é redigida à mão e **não serializa o
  resultado inteiro** do orquestrador (nunca `result.to_dict()`). Provado por
  33 testes novos (incl. integração pelo loop real e AST). Suíte: 851 → 884.

### Documentation (MC17-UX)
- Added Motor Council chat dry-run command specification for future
  `/conselho simular` (`docs/architecture/MOTOR_COUNCIL_CHAT_DRY_RUN_SPEC_v1.md`,
  20 seções): estado atual, contratos de entrada/saída, privacidade/redaction,
  flags proibidas, failure modes, integração com `CouncilOrchestratorDryRun` e
  `amigavel.py`, JSON futuro montado à mão (proibido `result.to_dict()`), plano
  de testes futuros e fases MC18-UX+. Ponteiro adicionado em
  `MOTOR_COUNCIL_UX_SPEC_v1.md`.

### Not changed (MC17-UX)
- No functional chat dry-run command enabled (`/conselho` segue desabilitado).
- No real engine execution enabled.
- No code/test/workflow changed; suíte permanece em 851.
- No PyPI publication; nenhuma tag ou release criada.

### Added (MC16-UX)
- Added disabled Motor Council chat command skeleton for the future
  `/conselho` UX. Aparece no `/ajuda` do chat amigável, mas nasce fail-closed:
  qualquer uso (`/conselho`, `/conselho simular ...`, etc.) devolve
  `[NOMOS-MC-CHAT-DISABLED]` + `CHAT_ENABLED=false` sem processar/ecoar o texto
  do usuário. Novo módulo puro `src/nomos/council/chat_disabled.py`
  (`handle_disabled_chat_command`, constante literal
  `MOTOR_COUNCIL_CHAT_ENABLED = False`); ramo `/conselho` no loop de
  `amigavel.py` delega ao handler.

### Security (MC16-UX)
- Motor Council chat remains fail-closed: no real engine execution, no
  persistence, no real policy/audit/vault calls, no orchestrator/harness call,
  no prompt echo, no env enable. Mensagens não relacionadas devolvem `None`.
  Provado por 23 testes novos (incl. integração pelo loop real e AST de
  pureza). Suíte: 828 → 851.

### Added (MC15-UX)
- Added `nomos conselho simular "texto"` as a redacted dry-run command backed
  by the Motor Council dry-run orchestrator (`CouncilOrchestratorDryRun`).
  Flags: `--modo rapido|balanceado|critico|paranoico` (paranoico ⇒ privado),
  `--privado`, `--json`, `--iniciante`, `--avancado`. Saída humana
  (`[NOMOS-MC-DRY-RUN]`/`[NOMOS-MC-GATE-BLOCKED]`) e JSON mínimo/redigido
  (`dry_run/allowed/blocked/would_execute/would_write_audit/private_mode/
  persist_allowed/failure_code`). Novo módulo `src/nomos/council/cli_dry_run.py`;
  o roteador de `conselho` em `cli.py` libera só `simular`, mantendo os demais
  subcomandos desabilitados.

### Security (MC15-UX)
- The Motor Council CLI still performs no real engine execution, persistence,
  real policy, real audit or real vault calls: `simular` chama apenas o
  orquestrador dry-run, nunca o harness real, e o roteamento acontece antes de
  `_paths()` (Vault/Policy/Audit não são construídos). O prompt nunca é ecoado
  (humano/JSON/erro); flags proibidas (`--real`/`--enable`/`--cloud`/…) e
  desconhecidas falham fechado (`[NOMOS-MC-CLI-DENIED]`). Provado por 29 testes
  novos (incl. AST de pureza). Suíte: 799 → 828.

### Added (MC14-UX)
- Added disabled Motor Council CLI skeleton for the future `nomos conselho`
  UX. O comando aparece no `nomos --help` ("pré-release, ainda DESABILITADO"),
  mas nasce fail-closed: qualquer uso devolve `[NOMOS-MC-CLI-DISABLED]` +
  `CLI_ENABLED=false` e não interpreta subcomando/prompt/flags. Novo módulo
  puro `src/nomos/council/cli_disabled.py` (constante literal
  `MOTOR_COUNCIL_CLI_ENABLED = False`, sem API de habilitação); `cli.py`
  curto-circuita `conselho` antes do argparse e de `_paths()`.

### Security (MC14-UX)
- Motor Council CLI remains fail-closed: no real engine execution, no
  persistence, no real policy/audit/vault calls, no orchestrator/harness call,
  no prompt echo, no env/flag bypass. Provado por 21 testes novos (incl. AST
  de pureza do módulo). Suíte: 778 → 799.

### Adicionado
- Índice técnico do Motor Council (`docs/architecture/MOTOR_COUNCIL_INDEX_v1.md`)
  consolidando as fases MC0–MC9: mapa de fases, mapa de arquitetura, arquivos
  criados, garantias de segurança/dry-run/modo privado/gate/audit, o
  travamento do harness de execução real, resumo da UX spec, progressão de
  testes (520 → 778), evidência de CI, quirks conhecidos do sandbox,
  não-escopo, riscos remanescentes e um checklist de prontidão para RC4.
- Notas de release em rascunho para `v1.3.0rc4` — Motor Council Dry-run
  (`docs/missions/RELEASE_NOTES_v1.3.0rc4_MOTOR_COUNCIL_DRY_RUN.md`).
- Rascunho de corpo de GitHub Release para `v1.3.0rc4`
  (`docs/missions/GITHUB_RELEASE_v1.3.0rc4_MOTOR_COUNCIL_DRY_RUN.md`).
- Fase MC11-RC4: validação completa de baseline, ancestry e conteúdo dos
  rascunhos RC4 antes de tag; reconciliação da numeração de fases futuras —
  `MC11-RC4` passa a ser a trilha de release engineering (tag/release/PyPI),
  e a trilha de UX prevista pelo MC9 foi renumerada de MC11–MC16 para
  `MC12-UX`–`MC17-UX` em `MOTOR_COUNCIL_UX_SPEC_v1.md`.

### Achado (MC11-RC4)
- `.github/workflows/release.yml` publica um GitHub Release automaticamente
  em qualquer push de tag `v*`. Reportado ao usuário antes de qualquer push
  de tag (ver `docs/missions/MOTOR_COUNCIL_MC11_RC4_TAG_PREPARATION.md`,
  seção 8); a decisão explícita do usuário foi prosseguir com a tag e
  corrigir o release automático depois, em vez de segurá-la.

### Publicado (MC11-RC4, pós-decisão do usuário)
- Tag anotada `v1.3.0rc4-motor-council-dry-run` criada e enviada, apontando
  para o commit já validado com CI 17/17.
- O push da tag disparou `release.yml`, que publicou um GitHub Release
  automaticamente. Ele saiu inicialmente `prerelease=false` e marcado como
  "latest" (diferente do padrão dos 4 releases anteriores, todos
  `prerelease=true`); corrigido via API para `prerelease=true` /
  `make_latest=false` — sem criação, edição de conteúdo ou remoção manual,
  apenas correção das duas flags de um release que o workflow já havia
  criado sozinho. Corpo do release permanece o texto genérico do template;
  melhorá-lo fica para `MC12-RC4`, assim como ajustar `release.yml` para não
  precisar dessa correção pós-hoc na próxima tag.

### Fixed (MC12-RC4)
- Corrected RC4 GitHub Release metadata/body to publish as pre-release, not
  latest: título trocado de `v1.3.0rc4-motor-council-dry-run` (genérico) para
  `NOMOS v1.3.0rc4 — Motor Council Dry-run`, corpo trocado do texto padrão do
  workflow pelo conteúdo técnico de `docs/missions/
  GITHUB_RELEASE_v1.3.0rc4_MOTOR_COUNCIL_DRY_RUN.md` (postura de segurança,
  `PYTEST=778`/`CI=17/17`, itens incluídos/não incluídos, instalação).
  `prerelease=true`/`draft=false`/`make_latest=false` reconfirmados;
  `/releases/latest` continua 404.
- Hardened release workflow so future RC tags are not published as
  latest/final: `.github/workflows/release.yml` ganhou um step
  `Resolve release flags` que decide `prerelease`/`make_latest` a partir do
  nome da tag (`*rc*` ⇒ `prerelease=true`/`make_latest=false`), eliminando a
  necessidade de correção manual pós-publicação na próxima tag `v*rc*`.

### Not changed
- Nenhum código de runtime alterado (`src/**` intocado).
- Nenhum teste alterado (`tests/**` intocado); suíte permanece em 778.
- Nenhum comando CLI ou chat implementado.
- Nenhuma tag movida, recriada ou apagada; nenhuma publicação no PyPI.
- Nenhum asset binário novo anexado ao release existente.

### Documentation (MC13-RC4)
- Aligned public README/docs with RC4 Motor Council dry-run status: nova seção
  `## Motor Council` no `README.md` deixando explícito que o Council está em
  dry-run/pre-release (sem execução real, sem CLI/chat, sem nuvem/rede/
  subprocess, policy gate/audit só dry-run, modo privado força
  `persist_allowed=false`), apontando para o índice técnico e a UX spec.
  Contagem de testes no README corrigida de 494 (obsoleta) para 778, e a nota
  de maturidade agora marca o RC4 como pre-release.
- Added post-release verification notes for `v1.3.0rc4-motor-council-dry-run`
  (`docs/missions/MOTOR_COUNCIL_MC13_RC4_POST_RELEASE_VERIFICATION.md`) e um
  bloco "Estado pós-release" em `MOTOR_COUNCIL_INDEX_v1.md`
  (`RC4_RELEASE_PUBLISHED=true`, `RC4_PRERELEASE=true`, `RC4_LATEST=false`,
  `RELEASE_WORKFLOW_RC_GUARD=true`, `README_PUBLIC_ALIGNMENT=done`).

### Not changed (MC13-RC4)
- No runtime code changed (`src/**` intocado).
- No tests changed (`tests/**` intocado); suíte permanece em 778.
- No CLI/chat command implemented.
- No PyPI publication; nenhuma tag criada/movida/apagada; nenhum workflow
  alterado nesta fase.

## [1.3.0rc16] — 2026-07-04 (Motor Council — Fase MC8: orquestrador dry-run)

### Adicionado (interno, sem wiring de runtime)
- `nomos.council.orchestrator`: orquestrador **SPEC/DRY-RUN** que compõe, em
  memória, provider local (MC3/MC4) → simulador offline (MC2) → policy gate
  (MC6) → audit envelope (MC7) num único fluxo. `CouncilOrchestratorDryRun`,
  `CouncilOrchestrationInput/Result/Step/Trace/Failure`,
  `CouncilOrchestrationStepName`, `OrchestrationFailureCode`.
- Trace metadata-only prova a ordem determinística: `INPUT_VALIDATED` →
  `LOCAL_PROVIDER_EVALUATED` → `CANDIDATES_CREATED` → `SIMULATOR_RAN` →
  `POLICY_GATE_EVALUATED` → `FINAL_ENVELOPE_CREATED` → `AUDIT_ENVELOPE_CREATED`
  → `ORCHESTRATION_COMPLETED`/`ORCHESTRATION_BLOCKED` — o gate **sempre** antes
  do envelope final, o audit envelope **sempre** depois do gate, mesmo quando
  bloqueado. `private_mode=true` propaga `persist_allowed=false` para o
  envelope final e para todos os envelopes de auditoria.
- `dry_run=true`, `would_execute=false`, `would_write_audit=false` SEMPRE.
  Fail-closed de ponta a ponta: A6, dado sensível, sem candidatos elegíveis ou
  exceção de um componente plugável (provider/simulador/gate/audit builder)
  todos resultam em `allowed=false`, com trace completo e conteúdo nulo no
  envelope final. Códigos `ORCH_*` (9) cobrindo entrada inválida, provider,
  simulador, gate, audit envelope e invariantes de modo privado/dry-run.
- **O módulo não importa o harness de execução real (MC5)** — nenhum caminho,
  direto ou indireto, para execução real. Provider padrão usa o adaptador
  dry-run (MC4). **Sem motor real, Ollama, subprocess, HTTP, cloud, SDK, FS,
  env, tempo ou random; sem policy/vault/audit/approval reais.**
- 54 testes novos (contratos, comportamentos obrigatórios, ordem do trace,
  fail-closed por exceção plugável, invariantes de modo privado/dry-run,
  segurança AST). Suíte: 778.

## [1.3.0rc15] — 2026-07-04 (Motor Council — Fase MC7: audit envelope privado)

### Adicionado (interno, sem wiring de runtime)
- `nomos.council.audit_envelope`: envelope de auditoria SPEC/DRY-RUN.
  `CouncilAuditEnvelope/Builder`, `CouncilAuditEventType`,
  `CouncilAuditRedactionProfile`, `CouncilAuditDryRunResult`,
  `CouncilAuditEnvelopeFailure`, e `run_offline_council_with_audit_envelope`.
- `dry_run=true` e `would_write_audit=false` SEMPRE (sem escrita real no audit,
  sem disco). **`private_mode=true` ⇒ `persist_allowed=false`** em todos os
  envelopes, com redação máxima. Metadata é **só contagens/failure_code**;
  chaves/valores sensíveis (prompt/content/api_key/token/bearer/engine_id…) são
  bloqueados (`AUDIT_ENVELOPE_SENSITIVE_METADATA`) e nunca aparecem em to_dict/
  to_json/repr/warnings. Envelope com escrita real ou não-redigido ⇒ negado.
- **Sem audit/vault/policy/approval reais, sem motor, HTTP, subprocess, cloud,
  SDK, FS, env, tempo ou random.** Determinístico.
- 31 testes novos (redação, private, no-write, metadata sensível, builder nunca
  inclui conteúdo, integração, segurança AST). Suíte: 724.

## [1.3.0rc14] — 2026-07-04 (Motor Council — Fase MC6: policy gate dry-run)

### Adicionado (interno, sem wiring de runtime)
- `nomos.council.policy_gate`: integração SPEC/DRY-RUN com o Policy Gate A0–A6.
  `CouncilPolicyGateDryRun`, `CouncilGateRequest/Decision`,
  `FinalResponseEnvelope`, `CouncilGateFailure`/`GateFailureCode`,
  `CouncilGateRisk`, e `run_offline_council_with_policy_gate`.
- Toda resposta final simulada só é liberada se o gate devolver `allowed=true`.
  `dry_run=true`, `would_call_real_policy=false`, `would_request_approval=false`
  SEMPRE. Fail-closed determinístico: arbiter bloqueado, conteúdo vazio, A6,
  aprovação humana exigida, dado sensível e A3+ ⇒ negado; A0/A1/A2 liberados.
  Gate negado ⇒ envelope sem conteúdo; modo privado ⇒ `persist_allowed=false`.
- **Sem policy/approval/vault/audit reais, sem motor, HTTP, subprocess, cloud,
  SDK, FS, env, tempo ou random**; conteúdo final nunca vaza (repr/serialização).
- 30 testes novos (decisões, envelope, integração, segurança AST). Suíte: 693.

## [1.3.0rc13] — 2026-07-04 (Motor Council — Fase MC5: harness fail-closed)

### Adicionado (interno, sem wiring de runtime)
- `nomos.council.local_harness`: harness de execução local **FAIL-CLOSED**.
  Constante literal `REAL_LOCAL_ENGINE_EXECUTION_ENABLED = False` (não vem de
  env/config/argumento; sem API de enable/activate/unlock/set_enabled).
  `LocalExecutionHarness`, `LocalExecutionRequest/Result/AttemptRecord`,
  `LocalExecutionFailure`, `ExecutionFailureCode`.
- Qualquer tentativa de execução real ⇒ `executed=false` e `candidate=null`
  SEMPRE; código `REAL_EXECUTION_DISABLED` (ou `REAL_EXECUTION_ENGINE_NOT_LOCAL`
  para motor não-local). Modo privado ⇒ `persist_allowed=false`. Env não ativa
  (módulo não lê variáveis do sistema). O dry-run do MC4 continua intacto.
- **Sem motor real, Ollama, subprocess, HTTP, cloud, SDK remoto, FS, env, tempo
  ou random**; prompt nunca é armazenado (só `prompt_chars`) nem vaza.
- 26 testes novos (fail-closed, flag literal via AST, env-não-ativa, sem API de
  ativação, dry-run intacto, provas de pureza). Suíte: 663.

## [1.3.0rc12] — 2026-07-04 (Motor Council — Fase MC4: adaptador local dry-run)

### Adicionado (interno, sem wiring de runtime)
- `nomos.council.local_adapter`: contrato de adaptador de motor local em
  **SPEC/DRY-RUN** — `LocalEngineAdapter` (Protocol), `DryRunLocalEngineAdapter`,
  `LocalEngineExecutionPlan`, `LocalEngineDryRunResult`,
  `LocalEngineIsolationProfile`, `LocalEngineAdapterPolicy`,
  `DryRunAdapterCandidateProvider`, `LocalAdapterFailure` e `AdapterFailureCode`.
- **Não executa nada**: `would_execute=false` e `dry_run=true` SEMPRE. Perfil de
  isolamento nega tudo por padrão (network/subprocess/filesystem/env/cloud/
  loopback) e qualquer permissão ⇒ erro. Política `dry_run_only`/`local_only`
  obrigatórias. Motor não-local/cloud/rede/prompt-grande ⇒ bloqueado com código
  próprio (ADAPTER_*), mapeado a CouncilFailureCode no provider.
- **Sem motor real, Ollama, subprocess, HTTP, cloud, SDK remoto, FS, env, tempo
  ou random**; juízes/árbitro/gate seguem simulados. Prompt nunca entra no plano,
  resultado, warnings, conteúdo ou repr. Determinístico.
- 29 testes novos (contratos + dry-run + provider + segurança AST, incl. ausência
  de mutação global). Suíte: 637.

## [1.3.0rc11] — 2026-07-04 (Motor Council — Fase MC3: contrato de provedor local)

### Adicionado (interno, sem wiring de runtime)
- `nomos.council.local_provider`: contrato refinado de provedor de candidatos
  LOCAIS — `LocalCandidateProvider` (Protocol), `DeterministicLocalCandidate
  Provider`, `LocalEngineDescriptor`, `LocalCandidateRequest/Result`,
  `LocalProviderFailure`, e `run_offline_council_with_local_provider`.
- Códigos de falha distintos por causa: cloud/rede ⇒
  `CLOUD_BLOCKED_BY_LOCAL_LOCK`; dado sensível sem motor capaz ⇒
  `SENSITIVE_DATA_CLOUD_DENIED`; sem motor local ⇒ `NO_ELIGIBLE_LOCAL_ENGINE`.
  `supports_sensitive_data` bloqueia prompts sensíveis em motor incapaz.
- **Sem motor real, sem Ollama/cloud/rede/SDK remoto, sem FS/env, sem tempo/
  random, sem policy/vault/audit reais, sem persistência, sem CLI/chat.** Juízes/
  árbitro/gate seguem simulados (MC2). Prompt nunca vaza (repr/to_dict/resultado).
- 31 testes novos (contratos + segurança, incl. prova AST de pureza e
  determinismo). Suíte: 608.

### Alterado
- Consolidação: `local_engine.py` (MC3 anterior) foi **superseded** por
  `local_provider.py` (contrato desta fase, com códigos de falha distintos) e
  removido, junto de seus testes, para não manter dois provedores paralelos.

## [1.3.0rc10] — 2026-07-04 (Motor Council — Fase MC3: integração de motor local)

### Adicionado (interno, sem wiring de runtime)
- `nomos.council.local_engine`: camada por CONTRATO que troca só a origem dos
  candidatos — `LocalCandidateProvider` (Protocol) + `DeterministicLocalCandidate
  Provider` (fake determinístico), `LocalEngineDescriptor/Eligibility/Failure`,
  `LocalCandidateRequest/Result`, e `run_offline_council_with_local_candidates`.
- Motores exigem prefixo `local:`; um motor com cloud/rede/não-local é
  **inelegível** (nunca usado). **Sem cloud, sem rede, sem SDK remoto
  (OpenAI/Anthropic/Ollama), sem FS, sem env, sem policy/vault/audit reais, sem
  persistência, sem CLI/chat.** Juízes/árbitro/gate continuam simulados (MC2).
- `simulator`: refatorado para expor `run_with_candidates(...)` (reutilizado
  pela integração local); `run()` delega — comportamento MC2 idêntico.
- Fail-closed: sem motor local elegível ⇒ `NO_ELIGIBLE_LOCAL_ENGINE` bloqueado;
  gate simulado negado ⇒ bloqueado. Invariantes MC1 preservadas (paranoid/
  sensível/privado). Prompt nunca vaza no repr/serialização.
- 29 testes novos (contratos + segurança, incl. prova AST de pureza). Suíte: 606.

## [1.3.0rc9] — 2026-07-04 (Motor Council — Fase MC2: simulador offline)

### Adicionado (interno, sem wiring de runtime)
- `nomos.council.simulator`: simulador OFFLINE determinístico do pipeline do
  Council (Risk → Policy → Candidatos(fixtures) → Reviews(fixtures) →
  Divergência → Árbitro → Gate simulado → Audit), puro sobre os modelos MC1.
  `OfflineCouncilSimulator/Input/Result`, `SimulatedEngineFixture/JudgeFixture/
  PolicyGateResult`.
- **Sem motor real, sem LLM, sem rede, sem persistência, sem policy/audit/vault
  reais, sem CLI/chat.** Fixtures obrigam prefixo `fixture:`. Failure codes
  determinísticos (sem candidatos, gate negado, divergência alta, alerta crítico,
  autojulgamento/juízes insuficientes, conselho desligado, falha de motor).
  Invariantes MC1 preservadas (paranoid→local-only, sensível→sem cloud,
  privado→sem persistência). Prompt nunca vaza em repr/serialização.
- 26 testes novos (contratos + segurança, incluindo prova AST de que o módulo
  não importa rede/subprocess/threading/asyncio/motor e não toca FS/policy/vault/
  audit). Suíte: 577. Determinismo provado (mesma entrada ⇒ mesma saída).

## [1.3.0rc8] — 2026-07-04 (Motor Council — Fase MC1: modelos de dados)

### Adicionado (interno, sem wiring de runtime)
- `nomos.council.models`: modelos de dados puros do Motor Council (stdlib-only),
  conforme docs/architecture/MOTOR_COUNCIL_SPEC_v1.md. 12 modelos (session,
  policy, risk, candidate, blind_review, judge_score, arbiter_decision,
  disagreement, audit_record + enums de modo/risco/confiança/divergência/falha).
- Invariantes de segurança por construção (fail-closed): paranoid⇒local-only,
  local_only⇒sem cloud, private_mode⇒sem persistência, dado sensível⇒cloud negada.
  `repr` de modelos com texto do usuário não vaza conteúdo; anonimização remove
  autoria; autojulgamento é detectável; scores 0–5 validados.
- **Sem execução de motor, sem I/O, sem rede, sem persistência, sem CLI/chat.**
  31 testes novos (contratos + segurança, incluindo prova de que o módulo não
  importa rede nem motor/LLM). Suíte: 551.

## [1.3.0rc7] — 2026-07-04 (hardening do audit log — âncora HMAC no cofre)

### Adicionado
- **Âncora HMAC da cadeia de auditoria** (`kernel/audit_anchor.py`), mitigando a
  lacuna divulgada na auditoria: a hash-chain (sem chave) não detectava
  **truncamento de cauda** nem reescrita completa por quem tem escrita.
  - HMAC-SHA256 sobre {schema, entries_count, chain_tip, log_id, created_at};
    a **chave vive no cofre** (Argon2id) — nunca em claro, nunca logada, nunca
    impressa em erro; acessada fail-closed. Não é defesa-teatro: quem não tem a
    passphrase não forja a âncora, mesmo com escrita no NOMOS_HOME.
  - `nomos logs verify` reporta o estado: LEGACY_UNANCHORED (WARN),
    ANCHORED_VALID (PASS), ANCHORED_INVALID / TAIL_TRUNCATED / ANCHOR_MISSING /
    CHAIN_CORRUPTED (FAIL), ANCHOR_UNVERIFIED (WARN, sem passphrase).
    `--cofre` valida o HMAC.
  - `nomos logs anchor` cria/atualiza a âncora (gate A3 + passphrase),
    idempotente; avisa que logs antigos não provam ausência de truncamento
    anterior; audita `audit.ancorado` (só metadados).
- `AuditLog.estado()` e `AuditLog.tip_em(n)` para a âncora.

### Segurança
- Logs legados sem âncora nunca passam em silêncio (WARN, não PASS). Cadeia já
  corrompida não é ancorada (não mascara corrupção pré-existente).

## [1.3.0rc6] — 2026-07-04 (correção de CI — gate POSIX no Windows)

### Corrigido
- **Último teste vermelho no Windows**: `test_vault2.py::test_lockout_arquivo_0600`
  verificava modo de arquivo `0600` (POSIX), que o Windows não aplica. Recebeu o
  mesmo gate `skipif(os.name=="nt")` já usado nos outros testes de permissão
  (vault, chaves, memory, skill_signing). Depois do rc5, as falhas do Windows
  caíram de 35 para 1; esta fecha a última.

## [1.3.0rc5] — 2026-07-04 (correção de CI — fins-de-linha no Windows)

### Corrigido
- **CI vermelho no Windows** (35 testes, todos "checksum divergente em main.py"):
  causa-raiz de fim-de-linha. Skills declaram sha256 dos próprios arquivos e a
  verificação lê bytes crus; no Windows, `write_text` grava CRLF, mudando os
  bytes e quebrando a integridade. Correções:
  - `.gitattributes` força LF (`* text=auto eol=lf`) — mantém as skills oficiais
    versionadas válidas no checkout Windows;
  - `skill_sdk.criar_skill` grava main.py/skill.json/README com `newline="\n"`
    (skill criada no Windows agora passa a própria verificação);
  - testes que geram main.py em runtime gravam LF determinístico.
  Provado localmente simulando CRLF (diverge) vs LF (confere). Sem afrouxar a
  verificação de integridade — os bytes seguem exatos, só determinísticos.

## [1.3.0rc4] — 2026-07-04 (F5+F6 do plano de validação)

### Adicionado
- **Rotina dry-run** (F5/ISSUE-023): `nomos rotinas executar --simular` mostra
  o que faria SEM executar nem marcar como feito; auditoria registra
  `rotina.simulada`. `prever_acao` descreve cada ação.
- **Smoke pós-instalação no CI** (F6/ISSUE-024): job que constrói o wheel,
  instala em ambiente limpo nos 3 SOs e roda `nomos doutor` como relatório de
  saúde.

### Corrigido
- **Agentes oficiais não vinham no wheel** (defeito pego pelo smoke da F6):
  movidos de `examples/` para `src/nomos/agents/oficiais/` e empacotados;
  `nomos agentes listar` agora funciona na instalação por wheel.

## [1.3.0rc3] — 2026-07-04 (F4 do plano de validação — UX)

### Adicionado
- **Memória tipada** (ISSUE-019): `remember_typed` com tipo (fato/preferência/
  tarefa/projeto/contato/decisão/regra), fonte e confiança; migração automática
  de bancos antigos sem perder nada; detecção de contradições.
- **Memórias candidatas** (ISSUE-020): "você quer que eu lembre disso?" —
  candidata não vira memória sem aprovação (propor/aprovar/descartar).
- **Erro humano** (ISSUE-021): `erros.explicar(codigo)` dá uma frase clara + o
  próximo passo para cada `[NOMOS-Exx]`; teste garante uma explicação por código.
- **Modo iniciante** (ISSUE-022): menu principal esconde o avançado; alterna
  com "avancado"/"iniciante".

## [1.3.0rc2] — 2026-07-04 (F3 do plano de validação — agentes locais)

### Adicionado
- **Agentes locais governados** (ISSUE 013–018), lacuna confirmada na
  validação. Regra inegociável **provada por teste**: agente NÃO é atalho para
  burlar política.
  - `AgentManifest`: ferramentas de uma **allowlist fechada**; o manifesto não
    pode declarar risco menor do que suas ferramentas exigem (fail-closed).
  - `AgentToolBoundary`: agente só acessa ferramenta do seu manifesto e toda
    ação passa pelo MESMO `policy.gate` A0–A6 do kernel — sem gate novo, sem
    herança de permissão entre agentes.
  - `AgentRegistry`: instalar/listar/ativar + sugestão por keyword (só do texto
    digitado).
  - **3 agentes oficiais** (examples/agents): pesquisador-local (A0),
    programador (A1), seguranca (A0), validados por teste.
- Comandos: `nomos agentes listar|info|ativar|desativar|diagnostico`.
- Auditoria por agente: uso e negação de ferramenta.

## [1.3.0rc1] — 2026-07-04 (F2 do plano de validação — histórico de conversas)

### Adicionado
- **Histórico de conversas** (ISSUE 006–012), lacuna confirmada na validação:
  conversas viram cidadãs de primeira classe (SQLite local 0600), com título e
  tags gerados localmente, busca híbrida (palavra-chave + significado), fixar,
  "não usar como memória", reabrir e continuar com contexto.
- **Modo privado/efêmero** (`/privado`): a conversa roda em store `:memory:` e
  **não toca o disco** — provado por teste que inspeciona o FS.
- **Retenção** configurável: conversas não fixadas expiram após N dias, só
  localmente, com aviso; fixadas nunca expiram.
- **Export/import cifrado** (Fernet + PBKDF2 600k): `nomos conversas
  exportar/importar`; senha errada/adulterado ⇒ nada importado.
- Comandos: `nomos conversas listar|abrir|buscar|esquecer|fixar|exportar|
  importar|retencao`. Chat: `/conversas /continuar <id> /fixar /privado`.

### Segurança
- Conversa privada não persiste; logs guardam só metadados (id/contagem),
  nunca texto; export exige aprovação (senha via TTY ou NOMOS_BACKUP_SENHA).

## [1.2.0rc2] — 2026-07-04 (F1 do plano de validação — endurecimento)

### Segurança
- **Anti prompt-injection** (ISSUE-001): conteúdo recuperado (memória/RAG) é
  ENVELOPADO com preâmbulo "isto é DADO, não instrução" e delimitadores únicos
  por chamada; marcadores embutidos no conteúdo são neutralizados. A oferta de
  skill por intenção passa a considerar SOMENTE o texto digitado pelo usuário
  (`prompt_guard.texto_confiavel`), nunca o conteúdo recuperado. 5 testes.
- **XSS do painel** (ISSUE-005): teste garante que nome com `<script>` sai
  escapado.

### Higiene / qualidade
- `.coverage` removido do versionamento e ignorado (ISSUE-002).
- Contagem de comandos corrigida (27→25) na documentação (ISSUE-003).
- **mypy** informativo no CI sobre o kernel, não bloqueante (ISSUE-004).

## [1.2.0rc1] — 2026-07-04 (fase v1.2 do ROADMAP_2)

### Adicionado
- **O agente age na conversa**: skills instaladas declaram `keywords` no
  manifesto e o chat OFERECE a skill certa quando a intenção bate — "posso
  usar a skill 'X' para isso? (sim/não)". "sim" executa pelo gate de sempre e
  o JSON vira resposta legível; "não" segue a conversa normal. Heurística
  local e determinística: nenhuma IA decide, skills desativadas/quebradas
  nunca são oferecidas.
- **`/skills usar <nome> [json]`** no chat: invocação explícita com o mesmo
  gate; JSON inválido tem erro claro.
- **Skill oficial nº 4 — `busca-arquivos`** (A0, só leitura): "onde está o
  contrato?" procura por nome e conteúdo com limites de varredura.
- **Auditoria da cadeia**: evento `skill.conversa` (nome, origem
  oferta/explicito, rc) — metadados, nunca o conteúdo do resultado.

## [1.1.0rc1] — 2026-07-04 (fase v1.1 do ROADMAP_2)

### Adicionado
- **Streaming de tokens**: a resposta aparece enquanto o motor local gera
  (Ollama via NDJSON e cérebro embutido via llama.cpp stream). Backend sem
  stream faz fallback honesto (resposta completa de uma vez); Ctrl+C no meio
  interrompe limpo e a resposta parcial NÃO vira memória. Nuvem continua
  não-stream (opt-in como sempre).
- **RAG local**: antes de responder, a busca híbrida puxa até 3 memórias
  relevantes para o contexto — com rodapé honesto "(usei N lembrança(s)
  suas)" no chat e no `nomos chat`. Instrução explícita ao motor: usar só se
  fizer sentido, nunca inventar além delas.
- **`/contexto`**: mostra EXATAMENTE o que foi enviado ao motor na última
  resposta, com segredos redigidos (padrões sk-/AKIA/JWT viram [REDIGIDO]).
- **Janela adaptativa**: conversa acima de 8k chars encolhe — o miolo antigo
  vira um resumo heurístico LOCAL (determinístico, sem custo de inferência);
  as mensagens recentes seguem intactas.

## [1.0.0rc2] — 2026-07-03 (fase v1.0.1 do ROADMAP_2)

### Adicionado
- **Boot instantâneo**: módulos pesados (cryptography/argon2/cognição) só
  carregam no comando que os usa — `nomos --version` caiu de 53 módulos
  pesados no boot para zero (~40 ms); teste determinístico garante que não
  regride.
- **`nomos doutor --consertar`**: aplica correções SEGURAS (pastas ausentes;
  localidade/policy/rotinas/estado corrompidos → recriados com padrão seguro,
  original preservado como `.corrompido`) com confirmação digitada
  ("CONSERTAR"); sem TTY lista e nega. Nada destrutivo, tudo auditado.
- **`nomos backup criar|restaurar|inspecionar`**: o NOMOS inteiro num arquivo
  cifrado (tar → Fernet + PBKDF2 600k; exclui `modelos/` re-baixáveis, com
  aviso). Restaurar em home com conteúdo exige "RESTAURAR" em TTY e preserva
  o atual em `.antes-restauro-<ts>/`; senha errada/adulterado ⇒ nada muda;
  caminhos do tar validados contra escape.
- **Códigos de erro pesquisáveis** `[NOMOS-Exx]` nos caminhos de erro
  principais + docs/ERROS.md; teste garante que todo código usado está
  catalogado E documentado.
- **Motor sem compilador**: `cerebro instalar` usa `--prefer-binary` e, ao
  falhar, explica o caminho (ferramentas de build ou Ollama).

## [1.0.0rc1] — 2026-07-03

### Adicionado
- **Modelo de ameaças formal** (docs/THREAT_MODEL.md): STRIDE → mitigação →
  teste que prova; riscos residuais declarados, não mascarados.
- **Cobertura no CI**: job dedicado com `--cov-fail-under=80`. Medição atual:
  kernel ≥92% (policy e localidade 100%), geral 83%.
- **Empacotamento**: templates prontos de Homebrew (`packaging/homebrew`) e
  winget (`packaging/winget`) para preencher na release final.

### Pendente para o 1.0.0 final (fora do código)
- Auditoria de segurança independente do kernel; CI verde no GitHub
  (pós-push); release pública; publicação nas lojas. Ver
  docs/missions/NOMOS_ROADMAP_EXECUTION_REPORT.md.

## [0.18.0] — 2026-07-03

### Adicionado
- **O roteador aprende com você, localmente**: `/bem` e `/mal` no chat (ou
  `nomos motores feedback <motor> bom|ruim`) registram votos por motor em
  `feedback.json` (0600). Motor mal avaliado é rebaixado na escolha; a
  confiança da decisão reflete sua experiência. Zero telemetria — o voto
  nunca sai da máquina, e a razão da escolha explica o efeito.
- **Visão no chat** (`/ver <imagem>`): descreve imagens com modelo de visão
  LOCAL (Ollama/llava, loopback apenas — host externo é recusado por
  projeto). Sem modelo: instrução honesta de 1 linha.
- **Catálogo do cérebro estendido**: nomos-pro (Qwen2.5 7B) e nomos-max
  (Llama 3.1 8B) para máquinas com 16+ GB — mesmo fluxo opt-in de download.
- **Pipeline paralelo** (`run_parallel`): etapas independentes em threads,
  com TODOS os gates decididos antes (uma negação cancela o lote inteiro
  antes de qualquer execução).

## [0.17.0] — 2026-07-03

### Adicionado
- **Painel local** (`nomos painel`): o NOMOS inteiro numa página do navegador
  — STATUS GERAL, check-up, motores por modalidade, skills, rotinas e os
  últimos eventos da auditoria. **Somente leitura** (POST ⇒ 405): agir
  continua no terminal e no painel de aprovações, com gate.
- Mesmas garantias do painel de aprovações: bind exclusivo em 127.0.0.1
  (outro host ⇒ recusa), URL com segmento secreto (sem ele ⇒ 404), HTML
  autossuficiente sem assets externos, erro interno nunca vaza detalhes.

## [0.16.0] — 2026-07-03

### Adicionado
- **Rotinas locais** (`nomos rotinas`): criar (com aprovação humana no gate
  A1 — rotina roda sozinha depois, então nasce só com seu sim), listar,
  pausar/retomar, remover, executar. Ações permitidas: registro fixo seguro
  (briefing, doutor, consolidar-memoria) ou `skill:<nome>` — skills que pedem
  aprovação NÃO rodam em rotina (fail-closed, por design).
- **Briefing do dia** (`nomos rotinas briefing`): tarefas e datas anotadas,
  rotinas configuradas e o próximo passo do doutor — 100% local.
- **`nomos rotinas agendar`**: mostra a linha de crontab/Agendador para VOCÊ
  colar — o NOMOS nunca altera o agendador do sistema sozinho.
- Cada rotina roda no máximo 1x por dia; arquivo corrompido ⇒ nada roda.

## [0.15.0] — 2026-07-03

### Adicionado
- **SDK de skills**: `nomos skills criar <nome>` gera esqueleto completo e
  válido (main.py com I/O JSON, skill.json v2 com checksums, README com
  assinatura e publicação). Nome validado; nunca sobrescreve.
- **I/O estruturado**: `nomos skills rodar <nome> --args '<json>'` — os
  argumentos chegam à skill por arquivo efêmero (limpo após a execução) e a
  resposta JSON é interpretável (`executar_json`).
- **Catálogo assinado**: catálogo local pode ser assinado (ed25519) por um
  publicador do trust store; assinatura inválida descarta o catálogo INTEIRO
  (fail-closed). `nomos skills atualizar` compara versões instaladas com o
  catálogo e informa — instalar continua manual, com gate.
- **3 skills oficiais de exemplo** em `examples/skills/` (organizador,
  lembrete, sistema-info): todas A0/risco baixo, validadas por teste.

## [0.14.0] — 2026-07-03

### Adicionado
- **Busca híbrida** (`memory search` e `/memoria buscar`): palavras-chave
  (comportamento clássico) + similaridade por significado via `semantica.py`
  — hashing local de n-gramas, zero dependência, zero rede, determinístico.
  Stopwords não dominam mais a fase de palavra-chave.
- **Backup cifrado de memórias**: `nomos memory exportar/importar <arquivo>`
  (Fernet + PBKDF2-SHA256 600k, sal por arquivo, 0600). Senha errada ou
  arquivo adulterado ⇒ nada importado; importar nunca apaga (deduplica).
- **Consolidação**: `nomos memory consolidar` extrai fatos, preferências e
  tarefas explícitas das conversas para notas duráveis (heurística local
  transparente, idempotente).

## [0.13.0] — 2026-07-03

### Adicionado
- **`nomos arquivo <caminho>`** e **`/arquivo`** no chat: lê txt/md/csv/json/
  log (e PDF com o extra opcional `nomos[arquivos]`), extrai pontos por
  heurística local transparente, resume com o motor local quando presente e
  — só com sua aprovação (A1) — salva o resumo ao lado do arquivo
  (`--salvar`). Sem cérebro: entrega os pontos e orienta, sem fingir resumo.
- **`/ouvir <áudio>`** no chat: transcreve com o whisper local, resume com o
  motor local e guarda na memória; sem whisper, orientação honesta em 1 linha.
- Limite de 5 MB por arquivo com mensagem clara; PDF escaneado (sem texto) é
  detectado e explicado.
- Pipeline de arquivos usa o EnginePipeline: etapas pela política, falha
  honesta, auditoria só com metadados e explicação final ("Nada saiu da sua
  máquina.").

## [0.12.0] — 2026-07-03

### Adicionado
- **CI no GitHub Actions**: pytest + ruff em ubuntu/macos/windows × Python
  3.10–3.13 (`.github/workflows/ci.yml`); badge no README.
- **Release automatizada** (`.github/workflows/release.yml`): em tag `v*`,
  valida a suíte, constrói wheel+sdist, gera `SHA256SUMS`, faz smoke do wheel
  e publica a release com os instaladores anexados.
- **Instaladores Windows**: `installer/install.ps1` e `uninstall.ps1` com os
  mesmos princípios fail-closed do Unix (checksum, backup, purge só com
  confirmação digitada). `install.sh` agora também instala a partir do wheel
  baixado da release (modo release) além do código-fonte (modo dev).
- **`nomos atualizar`**: checa a última versão publicada (api.github.com)
  apenas com o cadeado aberto + sua aprovação (gate A2); compara versões,
  mostra as novidades e o caminho manual. **Nunca baixa nem instala sozinho.**
- **Política anti-telemetria explícita** em docs/PRIVACIDADE.md, garantida
  por teste estático (allowlist de destinos externos justificada).
- Extra `dev` no pyproject (`pip install -e ".[dev]"`) e `[project.urls]`.

### Segurança
- Novo destino externo (`api.github.com`) adicionado à allowlist do teste
  fortaleza com justificativa — atrás do gate A2 e do cadeado só-local, como
  todos os demais. Nenhum caminho novo de autorização.

## [0.11.0] — 2026-07-03

### Adicionado
- **Menu principal amigável**: `nomos` (já configurado) abre menu numerado com
  10 opções; 1ª vez continua indo para o onboarding.
- **Skills amigáveis**: grupo `nomos skills` (menu, listar, instalar, remover,
  info, ativar, desativar, rodar, diagnostico) com status (ativa/inativa/
  quebrada/não confiável), risco (baixo/médio/alto), publicador e último uso.
- **Registry local de skills**: catálogo em `~/.nomos/registry/catalogo.json`
  (instalada × disponível × confiável × experimental).
- **Manifesto v2** de skill: description, entrypoint, risk_level (calculado se
  ausente — e nunca "afrouxável"), requires_approval, publisher,
  compatible_nomos_version, modalities, local_only_capable, cloud_required.
- **Execução governada de skills** (`nomos skills rodar`): só permissões
  declaradas, cada categoria pelo gate; rede cai no A2 (cadeado só-local);
  roda no sandbox.
- **Catálogo de motores v0.11** (12 modalidades: texto, codigo, raciocinio,
  resumo, memoria, voz_stt, voz_tts, imagem, visao, embeddings, ferramentas,
  roteamento) com custo, privacidade, velocidade, qualidade, chave e aprovação.
- **Roteador automático** (`engine_router`): local-first, honra dados
  sensíveis, nunca escolhe nuvem com só-local ligado, não inventa quando falta
  motor; produz `EngineRouteDecision` auditável. `nomos motores recomendar`,
  `auto on|off`, `testar`, `status`, `menu`, `diagnostico`.
- **Pipeline de motores** (`engine_pipeline`): etapas com política em cada
  passo, falha honesta na primeira negação, auditoria só de metadados,
  explicação simples ao usuário.
- **Doutor v0.11**: STATUS GERAL (PRONTO/PARCIAL/BLOQUEADO), checagem de
  Python, home, cofre, auditoria, localidade, cérebro, motores por modalidade,
  skills quebradas e **um** próximo passo recomendado.
- **Documentação real**: docs/INSTALL.md, MOTORES.md, SKILLS.md, ROTEADOR.md,
  PRIVACIDADE.md, USUARIO_INICIANTE.md + relatórios de missão em docs/missions/.
- **Testes**: novas suítes de skills/motores/roteador/pipeline/doutor e
  regressões de local-first, opt-in de nuvem e não-vazamento de segredo.

### Mantido (compatibilidade)
- Todos os comandos v0.10 funcionam sem mudança: `nomos skill ...`,
  `nomos motores`, `nomos motores usar`, `chat`, `vault`, `consent`, `run`,
  `memory`, `status`, `logs verify`, `doutor`, `cerebro`, `local`, `tema`,
  `chaves`, `approvals`, `start`.
- Políticas de segurança intactas: fail-closed, aprovação por TTY com palavra
  exata, redação de segredos, auditoria com cadeia de hash, sandbox isolado.

### Segurança
- Nenhum caminho novo de autorização: skills, roteador e pipeline usam o
  mesmo `gate()` de sempre. CI/non-interactive continua negando tudo sensível.

## [0.10.0] — anterior

- Kernel local-first (política A0–A6, cofre, auditoria, consentimento,
  localidade), cérebro leve embutido, cognição (router local→cloud opt-in,
  memória SQLite), skills assinadas, sandbox, UX simples em pt-BR (onboarding,
  chat amigável, doutor, tema, chaves). 246 testes.
