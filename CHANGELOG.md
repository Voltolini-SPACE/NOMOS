# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/). Datas em UTC.

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
