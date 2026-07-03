# NOMOS — Plano de Melhorias Reais (pós-v1.0rc1)

Base: v1.0.0rc1 publicada (410 testes, CI 3 SOs, release automatizada).
Critério de corte deste plano: **só entra o que muda a experiência de quem usa
todo dia ou a confiança de quem avalia o projeto**. Nada de feature de vitrine.
Formato: cada versão é uma missão `implementation-loop-100` com aceite
verificável. Princípios inegociáveis inalterados (local-first, fail-closed,
gate único, zero telemetria, kernel congelado).

## Diagnóstico honesto do que limita o NOMOS hoje

1. **A primeira conversa real tem atrito**: baixar o cérebro é fácil, mas o
   motor (`llama-cpp-python`) exige compilação — iniciante trava aí.
2. **A resposta chega "de uma vez"**: sem streaming de tokens, o agente parece
   lento mesmo quando não é.
3. **O agente sabe, mas não usa o que sabe**: o chat não puxa memórias
   relevantes para o contexto (a memória existe, o RAG não).
4. **O roteador decide, mas o chat não age**: skills instaladas não são
   oferecidas na conversa; o usuário precisa saber que existem.
5. **Rotinas dependem de alguém chamar `rotinas executar`**: proativo de
   verdade precisa de um executor contínuo opt-in.
6. **macOS/Windows têm sandbox fail-closed** (recusa executar): correto, mas
   reduz funcionalidade — dá para isolar melhor por plataforma.
7. **CLI carrega módulos pesados no boot**: `nomos --version` não deveria
   importar Router/Memory.
8. **`pip install nomos` ainda não existe** (só release do GitHub): PyPI é o
   canal que falta.

## Imediato — v1.0.1 "Ajustes que se sentem no primeiro minuto"

| # | Melhoria | Aceite verificável |
|---|---|---|
| 1 | **Lazy imports na CLI**: mover Router/Memory/providers para import dentro dos comandos | `time nomos --version` < 150 ms; teste de tempo no CI (limite folgado 400 ms) |
| 2 | **`nomos doutor --consertar`**: aplica só correções seguras (criar pastas, religar cadeado, recriar policy default se corrompida — com confirmação) | doutor detecta → consertar corrige → doutor fica PRONTO; nada destrutivo sem "sim" |
| 3 | **`nomos backup completo <arquivo>`**: todo o ~/.nomos cifrado (perfil, memórias, rotinas, feedback, trust) — não só memórias | roundtrip em máquina limpa restaura o agente inteiro; senha errada = nada |
| 4 | **Códigos de erro pesquisáveis** (`NOMOS-E012`) nas mensagens de falha + tabela em docs/ERROS.md | toda mensagem de erro da CLI carrega código; doc lista causa e correção |
| 5 | **Wheels do motor embutido na release**: anexar `llama-cpp-python` pré-compilada (mac arm64/x86, linux, win) ou instruções `--prefer-binary` testadas | `nomos cerebro instalar` conclui sem compilador nos 3 SOs (validado no CI) |

## v1.1 — "Conversa de verdade" (streaming + memória no contexto)

| Entrega | Detalhe |
|---|---|
| **Streaming de tokens** | Ollama e embutido: resposta aparece enquanto gera (chat e painel); Ctrl+C interrompe limpo |
| **RAG local no chat** | antes de responder, busca híbrida puxa até 3 memórias/notas relevantes para o system prompt — com rodapé honesto "usei 2 lembranças suas" |
| **`/contexto`** | mostra exatamente o que foi enviado ao motor (transparência total) |
| **Janela adaptativa** | contexto grande → resumo automático via pipeline (já existe) ligado por padrão |

Aceite: primeira palavra da resposta em <2 s com motor local; pergunta "qual o
nome do meu cachorro?" respondida a partir de nota antiga; `/contexto` nunca
mostra segredo (redação aplicada).

## v1.2 — "Agente que age" (skills na conversa)

| Entrega | Detalhe |
|---|---|
| **Oferta de skill na conversa** | intenção detectada (heurística local, mesma família do classificador) → "posso usar a skill 'organizador' para isso — quer? (sim/não)" → gate normal → resultado JSON vira resposta |
| **`/skills usar <nome> {json}`** | invocação explícita dentro do chat |
| **Skill de busca em arquivos** | oficial nº 4: indexa uma pasta aprovada (A0) e responde "onde está o contrato X?" |
| **Auditoria da cadeia** | evento único liga pergunta→skill→resultado (metadados) |

Aceite: fluxo pergunta→oferta→sim→gate→resultado em uma conversa; "não" nunca
executa nada; skill sensível continua exigindo aprovação por uso.

## v1.3 — "Sempre presente" (rotinas sem fricção)

| Entrega | Detalhe |
|---|---|
| **`nomos rotinas daemon`** | executor foreground opt-in (loop de 60 s chamando `executar_devidas`); Ctrl+C para; nada de daemon oculto |
| **Integração com o agendador do SO** | `rotinas agendar --instalar` gera E instala (com aprovação digitada) o launchd plist/systemd user unit/Task Scheduler XML; `--remover` desfaz |
| **Notificação nativa** | resultado do briefing vira notificação local (osascript/notify-send/burnt-toast), silenciável por rotina |
| **Rotina "consolidar memória semanal"** | pré-configurada, desligada por padrão |

Aceite: briefing chega às 8h sem terminal aberto (SO agenda, NOMOS executa);
desinstalar deixa zero resíduo; tudo auditado.

## v1.4 — "Painel completo" (um lugar só)

| Entrega | Detalhe |
|---|---|
| **Aprovações no painel principal** | unificar PanelServer no dashboard: pendências aparecem e são decididas ali (mesma fila single-use/TTL) |
| **Chat no painel** | conversa via navegador (POST autenticado pelo segredo da URL + token CSRF por sessão); mesmas regras do chat do terminal |
| **Rotinas e feedback no painel** | pausar/retomar rotina e votar 👍/👎 com os mesmos gates |
| **Modo acessível** | alto contraste + navegação por teclado + `prefers-reduced-motion` |

Aceite: usuário faz TUDO (conversar, aprovar, rotinas) sem terminal; bind
continua exclusivo 127.0.0.1; teste automatizado prova que POST sem segredo+token = recusa.

## v1.5 — "Confiança operacional" (o mundo confia)

| Entrega | Detalhe |
|---|---|
| **PyPI**: `pip install nomos` | publish job na release (trusted publishing OIDC, sem token guardado) |
| **CodeQL + Dependabot + pip-audit no CI** | supply chain vigiada por máquina |
| **SECURITY.md** | política de divulgação responsável + prazo de resposta |
| **Proteção de branch** | main só via PR com CI verde (documentado; config é do operador) |
| **i18n: inglês** | strings amigáveis centralizadas; `NOMOS_LANG=en` completo |
| **Sandbox melhor por plataforma** | macOS: `sandbox-exec`/Seatbelt como isolamento nativo; Windows: documentar S1 via Docker Desktop — sem afrouxar o fail-closed onde não houver garantia |

Aceite: `pip install nomos && nomos` funciona num Mac zerado; CodeQL sem
alertas altos; suíte com `NOMOS_LANG=en` passa; macOS executa skill A0 isolada
sem unshare.

## Ordem recomendada e por quê

```
v1.0.1 (1 dia)  →  v1.1 (conversa)  →  v1.2 (agir)  →  v1.3 (presença)
                                             │
                          v1.5 (confiança) ← ┴→ v1.4 (painel)
```

v1.0.1 primeiro porque são ganhos imediatos e baratos. v1.1/v1.2 atacam o
coração do produto (a conversa é o NOMOS). v1.3 entrega a promessa "proativo".
v1.4 e v1.5 podem correr em paralelo — uma é UX, a outra é reputação.

## O que este plano conscientemente NÃO faz

Sem app mobile (a base local não está madura para sync multi-dispositivo sem
comprometer o modelo de privacidade); sem plugins de nuvem além do já
existente opt-in; sem telemetria "para melhorar o produto" — nunca; sem
reescrita de kernel. Cada "não" acima é uma decisão, não um esquecimento.

## Regras de execução (herdadas e obrigatórias)

Uma missão por versão com `implementation-loop-100`; pytest 100% + ruff +
regressões de segurança ampliadas; smoke real; CHANGELOG + docs na mesma
entrega; relatório final com STATUS_FINAL evidenciado; kernel intocável salvo
justificativa de segurança com testes novos.
