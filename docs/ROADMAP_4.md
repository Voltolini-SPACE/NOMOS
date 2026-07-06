# NOMOS — Roadmap 4: Potência Real, MCPs e Pré-Integrações

**Base:** rc17 + MC31 (`main` com MCP server, arbitragem CLI+chat, evidências,
guardiões no CI, memória 2.0) · **Data:** 2026-07-06 · **Status:** proposto
**Antecessores:** ROADMAP (v0.x→v1.0) · ROADMAP_2 (v1.0→v1.5) · ROADMAP_3 (MC30/31)
**Missão de origem:** MC32 — "dar potência e funções reais ao sistema".

> Tese deste roadmap: o NOMOS já **governa** com excelência (política executável,
> evidências, dry-run, gates). A próxima fronteira é **fazer** — agir de verdade
> no computador do usuário — sem abrir mão de um milímetro da governança. Cada
> watt de potência nova nasce atrás de um gate A0–A6, com aprovação humana,
> evidência e teste. Potência sem governança é o que os outros fazem.

## 0. Fatos externos que ancoram este plano (pesquisados em 2026-07-06)

- **Microsoft OmniParser V2** (parsing de tela → GUI agents): roda local
  (Docker/FastAPI), ~0,8 s/frame numa RTX 4090, mínimo prático 4 GB VRAM
  (8 GB confortável), CPU 10–30× mais lento. **Licenças mistas**: icon_detect
  é **AGPL**, icon_caption é MIT ⇒ no NOMOS ele DEVE viver como **processo
  separado opt-in** (server loopback), nunca linkado ao código MIT.
- **MCP**: spec estável **2025-11-25**; release candidate **2026-07-28** traz
  núcleo stateless, **Tasks** (trabalho longo), **Extensions**, MCP Apps e
  endurecimento OAuth. Nosso server usa 2024-11-05 ⇒ upgrade planejado (M3),
  e o transporte local continua stdio (nosso caso) + Streamable HTTP.

## 1. Regras herdadas (invioláveis)

Local-first; A0–A6 fail-closed; aprovação humana para tudo sensível; evidência
por missão; zero telemetria; push/publicação humanos; componente AGPL nunca
linkado (só processo externo). Cada item abaixo = 1 missão loop-100.

---

## Trilha P — POTÊNCIA: o NOMOS que faz (não só responde)

**P1 · Executor de missões multi-passo (plano → aprovação → execução → evidência)**
Objetivo: `nomos missao executar "organizar meus downloads"` gera um PLANO
legível (passos, nível A de cada um, arquivos afetados), pede UMA aprovação
informada, executa passo a passo parando em qualquer falha, e fecha com pacote
de evidências automático (diff, hashes, log).
Base real: `kernel/evidencia.py`, `policy.gate`, `engine_pipeline.py`.
Risco: alto (escrita real) — mitigação: dry-run default (`--executar` explícito),
lista de diretórios permitidos, rollback por backup prévio dos afetados.
Pronto quando: missão de exemplo roda e2e com evidência verificável; teste prova
que sem aprovação NADA muda no disco.

**P2 · Skills de escrita (A1) com diff-prévia**
Objetivo: skills oficiais que ESCREVEM — organizador de pastas, renomeador em
lote, arquivador — sempre mostrando o diff/plano antes e aplicando só após "SIM".
Base: `ext/skills.py` (gate por permissão já existe), exemplos A0 atuais.
Pronto quando: 3 skills A1 oficiais com testes de recusa-sem-aprovação.

**P3 · Pipeline de documentos com saída estruturada**
Objetivo: `/arquivo` devolve JSON estruturado (título, entidades, datas, ações
sugeridas) além do resumo — vira insumo para rotinas e skills.
Base: `cognition/arquivos.py`, extras `[arquivos]`. Depende de I4/I5.
Pronto quando: PDF/nota fiscal de exemplo vira estrutura testada.

**P4 · Visão de tela assistida (OmniParser) — em 3 fases**
Objetivo: o NOMOS **enxerga a tela** e ajuda de verdade ("onde clico?", "leia
este erro", "que campo falta?").
- Fase 1 (LER): captura de tela **gateada por A4_DEVICE_SCREEN** a cada uso,
  parsing local via OmniParser (server loopback), resposta descreve elementos
  com coordenadas; imagem nunca sai da máquina; hash da captura na auditoria.
- Fase 2 (PROPOR): "para enviar, clique no botão 'Enviar' no canto inferior
  direito" — o humano executa; NOMOS nunca move o mouse.
- Fase 3 (AGIR, futuro distante): clique executado pelo NOMOS com aprovação
  POR AÇÃO + gravação de evidência; fora deste roadmap até 1 e 2 amadurecerem.
Base: padrão de motor externo já existe (SD WebUI/ComfyUI no catálogo);
`visao.py` valida loopback. AGPL isolado por processo (fato §0).
Pronto (F1) quando: `nomos tela descrever` funciona com o server OmniParser
ligado, degrada com instrução clara sem ele, e o gate A4 é provado por teste.

**P5 · Voz ponta a ponta local** *(herdado B4)* — `nomos ouvir`/`falar` com
Whisper/Piper; upgrade I2 opcional.

**P6 · Personas multi-agente executáveis** *(herdado B3)* — pesquisador/
programador/segurança roteáveis com boundary por manifesto e handoff com
evidência.

## Trilha M — MCPs: o NOMOS como cidadão do ecossistema

**M1 · MCP client (consumir servers locais)**
Objetivo: `nomos mcp conectar <config>` roda um server MCP local como
subprocesso (stdio) e expõe as tools dele como **capacidades externas** no
catálogo — cada tool mapeada a um nível A (filesystem→A0/A1, git→A1, web→A2)
e gateada na chamada.
Base: nosso protocolo já falado no server (MC31/C1); `skill_catalogo`.
Alvos iniciais: servers oficiais filesystem (com root confinado), git, sqlite.
Risco: médio-alto (código de terceiros) — mitigação: allowlist do comando a
executar, manifesto de risco obrigatório, aprovação na 1ª conexão + por tool
A1+, nunca auto-instalar (usuário instala o server; NOMOS só registra).
Pronto quando: filesystem-server lê pasta permitida via NOMOS com gate provado
e tool A1 (write_file) exige aprovação por chamada.

**M2 · Catálogo e trust store de MCPs**
Objetivo: `nomos mcp catalogo` — servers registrados com manifesto (comando,
tools, níveis A, o-que-sai-da-máquina), assinado no trust store local (mesma
cadeia das skills). Revogação a um comando.
Pronto quando: conectar server fora do catálogo exige confirmação explícita
"ACEITO O RISCO" e fica marcado como experimental.

**M3 · Server v2: upgrade de protocolo + Tasks**
Objetivo: acompanhar a spec (2025-11-25 já; adotar 2026-07-28 quando final):
negociação de versão, **Tasks** para missões longas (P1 exposto via MCP com
progresso), e tools de ESCRITA gateadas — a aprovação humana acontece no
painel de aprovações do NOMOS, nunca no cliente remoto.
Pronto quando: cliente MCP dispara `nomos_missao_executar` e a execução só
começa após aprovação no painel local; teste cobre negação.

**M4 · Transporte Streamable HTTP loopback-only**
Objetivo: clientes que não fazem stdio conectam via `http://127.0.0.1:<porta>`
com token de sessão (mesmo modelo do painel). Bind fora de loopback recusado
na construção (padrão painel_web).
Pronto quando: teste prova 401 sem token e recusa de bind externo.

**M5 · Ponte skills ⇄ MCP**
Objetivo: cada skill instalada aparece automaticamente como tool MCP (A0 direto;
A1+ atrás do gate); e um server MCP conectado pode ser "promovido" a skill com
manifesto gerado. Um só catálogo de capacidades, duas portas.

## Trilha I — PRÉ-INTEGRAÇÕES: motores locais novos no catálogo

| ID | Integração | Modalidade | Nível/Gate | Como entra |
|---|---|---|---|---|
| I1 | **OmniParser V2** (Microsoft) | visao-tela | A4 por captura | server FastAPI local (Docker/porta), processo separado (AGPL isolado), probe loopback no catálogo — base do P4 |
| I2 | **faster-whisper / whisper.cpp** | voz_stt | A0 | binário local alternativo ao whisper atual; benchmark decide default |
| I3 | **Embeddings locais** (gguf via llama.cpp, ex. nomic-embed) | memória semântica | A0 | extra `[cerebro]`; B5-fase-2: busca semântica + dedupe de candidatas |
| I4 | **OCR local** (RapidOCR/Tesseract) | leitura_arquivo | A0 | pipeline /arquivo para PDF-imagem e prints |
| I5 | **Conversor de docs local** (docling/markitdown) | leitura_arquivo | A0 | docx/pptx/xlsx → texto/estrutura para P3 |
| I6 | **SearXNG local** (busca web self-hosted) | pesquisa | **A2 por consulta** | opt-in duro: cadeado aberto + aprovação; resultados viram contexto com fonte |
| I7 | **VLM local de uso geral** (ex. Qwen-VL via Ollama) | visao | A0 | já meio-suportado (visao-ollama); ampliar modelos homologados |

Regra da trilha I: toda integração entra como **motor no catálogo** (probe de
prontidão, custo, privacidade, qualidade), aparece no `nomos motores listar`,
no painel e no roteador explicável — nunca como dependência obrigatória.

## Trilha Q — Qualidade e prova de potência

**Q1 · Bancada local de motores** — `nomos motores medir`: latência/1º-token e
qualidade em golden-set local; resultado alimenta o ranking do roteador (hoje
heurístico + feedback). **Q2 · Harness de avaliação** — respostas do golden-set
avaliadas pela arbitragem (juízes cegos) para regressão de qualidade.
**Q3 · Extras de instalação** — `nomos[tela]`, `nomos[voz]`, `nomos[docs]`:
potência é opt-in até no pip. **Q4 · Fuzz leve do MCP server** — entradas
malformadas nunca derrubam o loop (ampliar o teste -32700 atual).

---

## Priorização recomendada (12 missões, ordem)

| # | Missão | Por quê nesta ordem |
|---|---|---|
| 1 | M1 MCP client | destrava um ecossistema inteiro de capacidades com UM esforço |
| 2 | P1 Executor de missões | é a definição de "funções reais" — e usa tudo que já existe |
| 3 | I4+I5 OCR+docs locais | potência imediata no /arquivo, risco A0 |
| 4 | P2 Skills A1 com diff-prévia | escrita governada; prova o modelo de aprovação |
| 5 | I1 OmniParser F1 (ler tela) | o "uau" visível; base do P4 |
| 6 | P4-F2 propor ação na tela | assistência real sem risco de automação |
| 7 | M3 Server v2 + Tasks | missões longas viram serviço para outros agentes |
| 8 | I3 Embeddings locais | memória semântica (B5-fase-2) |
| 9 | P5 Voz e2e | demo local-first perfeita |
| 10 | M2+M5 Catálogo/trust + ponte | consolida o modelo de confiança |
| 11 | Q1+Q2 Bancada e harness | roteador deixa de ser só heurística |
| 12 | P6 Personas | multi-agente com boundary — coroa a governança |

Dependências: P4→I1; P3→I4/I5; M3→P1; M5→M1+M2; Q2→arbitragem (pronta).
M4 e I6 são satélites (encaixar quando houver demanda). P4-F3 fica FORA até
F1/F2 rodarem meses em produção pessoal.

## Anti-metas (continuam)

Telemetria zero; nuvem nunca default; nenhuma ação de escrita/clique sem
aprovação humana explícita; nada de auto-instalar servers/modelos; AGPL jamais
linkado (só processo externo); navegador automatizado segue fora.

## Template de missão (colar e executar)

```text
MISSÃO: <ID> — <nome> (docs/ROADMAP_4.md)
USAR SKILL: implementation-loop-100
CONTEXTO: NOMOS main pós-MC31; item <ID> com objetivo/risco/pronto do roadmap
ESCOPO: o item, seus testes e docs · FORA: push, telemetria, defaults de nuvem,
        qualquer execução sem gate
CRITÉRIOS: "Pronto quando" do item + suíte verde + ruff + gates dos agentes +
           pacote de evidência da missão
```

## Fontes (§0)

- OmniParser: github.com/microsoft/OmniParser · huggingface.co/microsoft/OmniParser-v2.0
  (LICENSE icon_detect: AGPL; icon_caption: MIT) · replicate.com/microsoft/omniparser-v2 ·
  codersera.com (guia Windows) · stable-learn.com (latência V2)
- MCP: modelcontextprotocol.io/specification/2025-11-25 ·
  blog.modelcontextprotocol.io (RC 2026-07-28; roadmap 2026)
