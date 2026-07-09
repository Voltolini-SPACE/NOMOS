# EXTERNAL MEMORY REPO AUDIT — MC28

Auditoria estática do repositório externo **`claude-mem`** como referência
técnica para o desenho do **NOMOS Memory Engine V1**. A missão **não** instala,
não executa e não integra o plugin externo — apenas o lê em sandbox isolada e
extrai padrões conceituais.

| Campo | Valor |
|---|---|
| `EXTERNAL_REPO_URL` | https://github.com/thedotmack/claude-mem |
| Versão auditada | `13.10.2` (clonada com `--depth 1` em `/tmp/nomos_external_audit`) |
| `EXTERNAL_LICENSE` | Apache-2.0 (autor: Alex Newman) |
| Stack | Node.js ≥ 20.12 + Bun ≥ 1.0, TypeScript |
| Método | `git clone` em `/tmp` → leitura estática (`find`, `grep`, `cat`) — **sem executar nada** |
| `CODE_COPY_ALLOWED` | **NO** |
| `CONCEPT_REFERENCE_ALLOWED` | **YES** |

## 1. Arquitetura encontrada (`ARCHITECTURE_FOUND`)

Documentada em `docs/architecture-overview.md` do repo externo:

```
Claude Code (host)
  └─ Hook System — Setup + 5 eventos de ciclo de vida (auto-executa a cada startup)
CLI Layer (Bun)  — bun-runner, hook-command, handlers
Worker Daemon    — Express, porta por usuário 37700+(uid%100)
                   SessionManager · SDKAgent (Claude Agent SDK) · SearchManager
                   ProcessRegistry (gestão de subprocessos) · ChromaSync
Storage          — SQLite (claude-mem.db) + ChromaDB (embeddings) + MCP Server
                   + Postgres (server-beta multi-tenant: teams/projects)
```

- **`MEMORY_FORMAT_FOUND`**: SQLite com tabelas `observations`, `session_summaries`,
  `user_prompts`, `pending_messages` + tabelas virtuais **FTS5**; embeddings
  vetoriais em **ChromaDB**. Compactação = "session summaries" gerados por um
  **agente LLM** (SDKAgent).
- **`HOOKS_FOUND`**: SIM — 6 hooks (`Setup`, `SessionStart`, `UserPromptSubmit`,
  `PostToolUse`, `Summary`, `SessionEnd`) que disparam **automaticamente**.
- **`NETWORK_USAGE_FOUND`**: SIM — worker HTTP (Express), APIs `/api/sessions/*`,
  SSE para UI, server-beta em Postgres, Discord release-notify, deploy Vercel.
- **`SECRET_HANDLING_FOUND`**: usa `process.env` extensivamente; `SECURITY.md`
  descreve superfície de injeção de comando (git/process) mitigada com
  `shell:false` + args em array.
- **`INSTALL_RISK`**: ALTO — `npx claude-mem install` instala Bun e uv **globais**,
  roda `bun install` no cache do plugin, grava marcador de versão; há
  `postinstall`/`preinstall`.
- **`RUNTIME_RISK`**: ALTO — daemon persistente, subprocessos, rede local, banco
  vetorial, hooks automáticos.

### Superfície de risco (contagem por `grep`, repo externo inteiro)

| padrão | ocorrências | padrão | ocorrências |
|---|---:|---|---:|
| `spawn` | 688 | `process.env` | 629 |
| `child_process` | 91 | `subprocess` | 98 |
| `execSync` | 86 | `https://` | 2325 |
| `hooks` | 1031 | `http://` | 396 |
| `postinstall` | 40 | `preinstall` | 3 |
| `rm -rf` | 47 | `curl ` | 170 |

## 2. Matriz comparativa (decisão por feature)

| Feature externa | Como funciona no claude-mem | Risco | Utilidade p/ NOMOS | Nossa decisão |
|---|---|---|---|---|
| **Formato de memória** | SQLite + FTS5 + ChromaDB (vetorial) | Médio (deps pesadas: Chroma/embeddings) | Alta (estrutura + busca) | **Reimplementar** em JSONL append-only stdlib; sem banco vetorial |
| **Captura** | Hooks automáticos em cada evento do Claude Code | Alto (executa sem consentimento) | Média | **Rejeitar automação**; captura só por **CLI explícita** humana |
| **Recuperação de contexto** | Injeção semântica via worker/SDK no SessionStart | Alto (rede + LLM) | Alta (conceito) | **Adotar conceito**: `--context` determinístico, offline, curto |
| **Compactação** | Resumo por **agente LLM** (SDKAgent) | Alto (LLM, custo, rede) | Alta (conceito) | **Adotar conceito**: compactação **determinística** sem LLM; preserva bruto |
| **Integração Claude Code** | Hooks + MCP server + worker | Alto | Média | **Doc + CLI**; protocolo manual em `CLAUDE_MEMORY_USAGE.md` (sem hooks) |
| **Hooks** | 6 hooks disparam a cada startup | Alto | Baixa | **Rejeitar** — nada roda automático no NOMOS |
| **Instalação** | `npx install` → Bun/uv globais, `bun install`, postinstall | Alto | Nenhuma | **Rejeitar** — motor é módulo Python nativo, zero install extra |
| **Armazenamento** | `~/.claude-mem/…` (SQLite + Chroma + logs) | Médio | Alta (padrão de home) | **Adotar padrão local**: `~/.nomos/memory/*.jsonl` (0600) |
| **Tratamento de segredos** | `process.env`, sem filtro de admissão de segredo | Alto (vazamento) | — | **Superar**: política **fail-closed** que **recusa** segredos/PII antes de gravar |
| **Dependências** | Node, Bun, uv, Express, ChromaDB, Postgres | Alto | Nenhuma | **Rejeitar** — só stdlib do Python |
| **Risco de regressão** | Alto (daemon, migrations, muitos módulos) | Alto | — | **Isolar**: pacote novo `nomos/memory`, nada importa dele |
| **Risco de vazamento** | Rede + Discord + server-beta | Alto | — | **Zerar**: `NO_NETWORK_RUNTIME`, egress zero |
| **Facilidade de rollback** | Baixa (daemon, install global, banco) | Alto | — | **Alta**: apagar `nomos/memory/` remove tudo, sem efeito colateral |
| **Custo de tokens** | Compactação por LLM consome tokens | Médio/Alto | — | **Zero**: compactação e contexto determinísticos, sem LLM |
| **Simplicidade operacional** | Baixa (Bun/worker/Chroma/Docker) | — | — | **Alta**: 1 comando `python -m nomos.memory.cli` |
| **Compatível com dry-run** | Não (captura/escrita automáticas) | Alto | — | **Sim**: `--dry-run` é o **padrão absoluto**; grava só com `--apply` |
| **Compatível com local-first** | Parcial (tem server-beta/rede) | Médio | — | **Total**: 100% local, arquivos versionáveis e auditáveis |

## 3. Conceitos aproveitados (apenas ideias, zero código)

1. **Compactação de sessão** → resumo derivado que reduz custo de contexto —
   reimplementado **determinístico** (sem LLM), preservando o histórico bruto.
2. **Injeção de contexto na retomada** → nosso `--context` gera um bloco curto.
3. **Tags de proveniência** (`source`) → nosso campo `source`
   (`manual|session_summary|mission_result|handoff|repo_audit`).
4. **Home local dedicada** → `~/.nomos/memory/` (espelha o padrão, sem Chroma).
5. **Busca/índice estruturado** → `memory.index.json` simples (sem FTS/vetores).

## 4. O que foi rejeitado (e por quê)

- **Daemon/worker, servidor Express, server-beta Postgres, ChromaDB** → violam
  `NO_NETWORK_RUNTIME` e `LOCAL_FIRST`; deps pesadas; rollback difícil.
- **Hooks automáticos** → executam sem consentimento; violam `DRY_RUN_DEFAULT`.
- **Instalação global (Bun/uv), postinstall** → violam `NO_EXTERNAL_PLUGIN_IN_PROD`.
- **Compactação por LLM** → custo de tokens, rede, não determinística.
- **`process.env` sem filtro / Discord notify / Vercel** → risco de vazamento.

## 5. Por que NÃO instalamos o plugin externo

`claude-mem` é um sistema distribuído (daemon + rede + banco vetorial + hooks +
install global). Instalá-lo em produção contraria diretamente os requisitos da
missão: `LOCAL_FIRST`, `NO_NETWORK_RUNTIME`, `NO_EXTERNAL_PLUGIN_IN_PROD`,
`DRY_RUN_DEFAULT`, `ROLLBACK_READY`. O valor real dele para o NOMOS é
**conceitual**, e esse valor foi extraído sem executar nem copiar código.

## 6. Arquitetura escolhida (`ARCHITECTURE_DECISION`)

**Motor próprio `nomos.memory`, stdlib-only, isolado**, com camadas claras:
`store` · `policy` (fail-closed) · `compactor` (determinístico) ·
`context_builder` · `report` · `engine` · `cli`. Detalhes em
[`NOMOS_MEMORY_ENGINE.md`](NOMOS_MEMORY_ENGINE.md).

`EXTERNAL_PLUGIN_INSTALLED=NO` · `EXTERNAL_CODE_COPIED=NO` ·
`INSPIRED_BY_EXTERNAL_AUDIT=YES` · `NOT_DEPENDENT_ON_EXTERNAL_PLUGIN=YES`
