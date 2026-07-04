# SPEC — Missão v1.1 "Conversa de verdade" (streaming + RAG local)

(versão de pacote: 1.1.0rc1)

## Objetivo
A conversa deixa de parecer lenta (tokens aparecem enquanto o motor gera) e o
agente passa a USAR o que lembra (memórias relevantes entram no contexto),
com transparência total (`/contexto`) e janela adaptativa.

## Escopo incluído
1. **Streaming**: `OllamaProvider.chat_stream` (NDJSON) e
   `EmbeddedProvider.chat_stream` (llama-cpp stream=True) com callback
   `on_token`; `Router.chat_stream` local-first (sem stream => fallback
   honesto para chat normal); chat amigável imprime token a token; Ctrl+C
   durante o stream interrompe limpo e NÃO grava memória da resposta parcial.
2. **RAG local**: `cognition/rag.py` — `contexto_relevante(mem, pergunta)`
   puxa até 3 memórias (busca híbrida) para um bloco de sistema; rodapé
   honesto no chat: "(usei N lembrança(s) suas)"; também no `nomos chat`.
3. **`/contexto`**: mostra EXATAMENTE as mensagens da última chamada ao motor,
   passadas por `redact_text` (segredo nunca aparece nem aí).
4. **Janela adaptativa**: `rag.encolher_contexto(mensagens, limite)` — acima
   do limite, mensagens antigas viram um resumo heurístico local (pontos) e
   só as recentes seguem inteiras; ligado por padrão no chat.

## Fora de escopo
Streaming da rota cloud (continua não-stream, opt-in como sempre); RAG sobre
arquivos externos (é a v1.2, via skill); painel com chat (v1.4).

## Arquivos que poderei alterar
`src/nomos/cognition/providers.py` (aditivo), `src/nomos/cognition/embutido.py`
(aditivo), `src/nomos/cognition/router.py` (aditivo: chat_stream),
`src/nomos/cognition/rag.py` (novo), `src/nomos/simple/amigavel.py`,
`src/nomos/cli.py` (RAG no cmd_chat), versão/CHANGELOG/README,
`tests/test_v11_conversa.py` (novo).

## Arquivos proibidos
Kernel; testes existentes (test_chat_ux/test_router intactos — o caminho
não-stream é preservado byte a byte para compat).

## Critérios de aceite
| # | Critério | Verificação |
|---|---|---|
| 1 | tokens chegam ANTES da resposta completa | fake provider: ordem dos callbacks registrada |
| 2 | Ctrl+C no meio do stream: loop segue, memória NÃO grava parcial | teste do chat com stream que interrompe |
| 3 | "qual o nome do meu cachorro?" respondida a partir de nota antiga | fake router captura system prompt com a nota |
| 4 | rodapé honesto com contagem de lembranças | tela do chat |
| 5 | `/contexto` mostra as mensagens com segredos REDIGIDOS | nota com padrão sk- vira [REDIGIDO] |
| 6 | contexto acima do limite encolhe com resumo local | teste unitário de encolher_contexto |
| 7 | rota sem stream continua funcionando (compat) | suíte antiga verde sem alteração |
| 8 | suíte 100% + ruff | pytest/ruff |

## Riscos
Streaming parseando NDJSON parcial — mitigado com parser linha a linha e
testes com transporte fake. Compat do chat amigável — testes antigos cobrem.

## Rollback
Git (1 commit); caminho não-stream intacto como fallback permanente.
