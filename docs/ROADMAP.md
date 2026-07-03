# NOMOS — Plano de Evolução (v0.12 → v1.0)

> **Execução (2026-07-03)**: v0.12–v0.18 e v1.0-rc1 entregues e commitadas
> (410 testes, kernel intocado). Pendências externas do 1.0.0 final em
> [missions/NOMOS_ROADMAP_EXECUTION_REPORT.md](missions/NOMOS_ROADMAP_EXECUTION_REPORT.md).

Base: v0.11.0 (commit 877ca7a, 341 testes, ruff limpo).
Cada versão é uma missão executável com `implementation-loop-100`: spec →
implementar → testar → validar → evidenciar. Nenhuma fase pode enfraquecer os
princípios: local-first, fail-closed, aprovação humana, zero vazamento de
segredo, zero bypass, compatibilidade com comandos anteriores.

## Visão

Sair de "CLI local segura e amigável" para **o agente pessoal local que uma
pessoa comum usa todo dia**: instala em 1 clique, conversa por voz e texto,
entende arquivos, lembra de verdade, executa rotinas, tem ecossistema de
skills — tudo sem entregar dados a ninguém.

O diferencial competitivo do NOMOS não é ter mais features que assistentes de
nuvem; é ser o único que faz isso **com prova de privacidade** (política,
auditoria e testes — não promessa de marketing).

---

## v0.12 — Distribuição real ("qualquer pessoa instala")

O maior gargalo hoje não é código: é chegada. Sem release, só devs usam.

| Entrega | Detalhe |
|---|---|
| CI no GitHub | Actions: pytest + ruff em matriz Linux/macOS/Windows × Python 3.10–3.13; badge no README |
| Release automatizada | wheel + sdist + `SHA256SUMS` + tag assinada; release notes do CHANGELOG |
| Instaladores 1-clique | evoluir `installer/` (script Mac/Linux, .bat/.ps1 Windows) e anexar à release |
| `nomos atualizar` | checa versão nova (egress opt-in via gate A2), mostra changelog; **nunca** auto-atualiza |
| Telemetria: NÃO | decisão explícita documentada — zero telemetria, para sempre |

Aceite: instalar do zero num SO limpo em <3 min só seguindo o README; CI verde
nos 3 SOs; `pip install nomos-0.12.0-py3-none-any.whl && nomos doutor` = PRONTO/PARCIAL.

## v0.13 — Arquivos e voz de ponta a ponta (pipelines viram produto)

O `engine_pipeline` existe; agora vira experiência de usuário.

| Entrega | Detalhe |
|---|---|
| `nomos arquivo <caminho>` e `/arquivo` | ler (A0) → extrair pontos → resumir → sugerir ação; txt/md/pdf locais; salvar resumo pede A1 |
| `/ouvir <audio>` | whisper local → resumir → memória (o exemplo canônico da missão v0.11, agora real) |
| `/falar` melhorado | TTS da última resposta, não só texto avulso |
| Explicação de pipeline no chat | "Usei: transcrever (local) → resumir (local). Nada saiu da máquina." |
| Progresso honesto | etapas longas mostram o que está acontecendo |

Aceite: usuário arrasta um PDF e recebe resumo com fonte local; sem motor de
voz, resposta honesta com instrução de 1 linha; auditoria só com metadados.

## v0.14 — Memória de verdade (o agente que lembra)

Hoje a memória é FTS5 (palavra-chave). O salto: memória semântica local.

| Entrega | Detalhe |
|---|---|
| Embeddings locais | modelo pequeno de embeddings via llama.cpp/ONNX (~30–80 MB, baixado como o cérebro, com aprovação) |
| Busca híbrida | FTS5 + similaridade; fallback transparente para FTS5 puro |
| Memória estruturada | tipos: fato, preferência, tarefa, pessoa; extração automática pós-conversa (pipeline local) |
| Consolidação | resumir conversas antigas em memórias duráveis (roda local, com aviso) |
| Backup cifrado | `nomos memoria exportar/importar` — arquivo único cifrado com a senha-mestra |

Aceite: "o que eu disse sobre X mês passado?" encontra por significado, não só
palavra exata; exportar+importar num segundo computador preserva tudo.

## v0.15 — Ecossistema de skills (de recurso a plataforma)

| Entrega | Detalhe |
|---|---|
| `nomos skills criar <nome>` | gera esqueleto com manifesto v2, checksums, teste e assinatura guiada — SDK em 1 comando |
| I/O estruturado | skill recebe argumentos JSON via stdin e devolve JSON; chat consegue invocar skill como ferramenta (gate por uso) |
| Catálogo assinado | formato de catálogo com assinatura de publicador; `nomos skills atualizar` (opt-in, nunca automático) |
| 3 skills oficiais | organizador de pasta (A0/A1), lembretes (memória), relatório de sistema (A0) — exemplos vivos do SDK |
| Skill ↔ roteador | skill declara `modalities`; aparece em `ferramentas` no catálogo de motores |

Aceite: dev cria e assina uma skill funcional em <10 min; skill sem permissão
declarada continua não conseguindo nada (testes de regressão ampliados).

## v0.16 — Agente proativo (rotinas locais)

| Entrega | Detalhe |
|---|---|
| Rotinas | `nomos rotina criar "briefing às 8h"` — agendador local (sem cron do sistema); cada rotina aprovada na criação, executa só o pré-aprovado |
| Briefing do dia | pipeline: memórias recentes + tarefas + lembretes → resumo matinal local |
| Notificações locais | aviso nativo do SO (sem rede); silenciável |
| Painel de rotinas | listar/pausar/remover; auditoria de cada execução |

Aceite: rotina roda no horário com a máquina ligada; nada executa além do
escopo aprovado; desligar uma rotina é 1 comando.

## v0.17 — Interface para humanos (além do terminal)

| Entrega | Detalhe |
|---|---|
| Painel web local | evoluir `PanelServer` (já existe p/ aprovações): chat, doutor, motores, skills, decisões do roteador e auditoria — servido só em 127.0.0.1 |
| TUI opcional | interface de terminal rica para quem prefere teclado |
| Acessibilidade | alto contraste, fonte ajustável, navegação por teclado |
| `nomos painel` | abre o navegador no painel local |

Aceite: usuária que nunca abriu terminal usa o NOMOS inteiro pelo painel;
nenhuma porta exposta fora do loopback (teste automatizado).

## v0.18 — Cognição avançada (motores maiores, roteador que aprende)

| Entrega | Detalhe |
|---|---|
| Modelos maiores no embutido | catálogo estendido (7B/8B quantizados) com recomendação por RAM real |
| Visão no chat | `/ver <imagem>` usando modelo de visão local quando presente |
| Feedback do usuário | 👍/👎 por resposta → registro LOCAL por motor → ajusta `confidence` do roteador (sem telemetria) |
| Roteador contextual | usa histórico de sucesso local por (modalidade × motor) na ordenação |
| Paralelismo de pipeline | etapas independentes em paralelo, mantendo gate por etapa |

Aceite: com feedback negativo repetido num motor, o roteador troca a
recomendação e explica por quê; decisão continua 100% auditável.

## v1.0 — Consolidação e confiança pública

| Entrega | Detalhe |
|---|---|
| Threat model formal | documento STRIDE-like; ataques considerados e mitigação apontando para teste que prova |
| Cobertura medida | pytest-cov no CI; meta ≥90% no kernel, ≥80% geral |
| Auditoria externa | revisão de segurança independente do kernel (vault, policy, audit, sandbox) |
| Empacotamento | Homebrew, winget e AUR/apt quando viável |
| Site + docs | página simples com o guia do iniciante e demonstração honesta |
| Política de suporte | versões suportadas, ciclo de release, SLA de correção de segurança |

Aceite: instalação por gerenciador de pacote; relatório de auditoria público;
v1.0 é a promessa "local por lei" com prova de terceiros.

---

## Transversais (valem para toda versão)

- **Regra de ouro de escopo**: kernel (`policy/vault/audit/localidade/consent/
  sandbox/signing`) só muda com justificativa de segurança + testes novos.
- **Cada versão adiciona regressões**: local-first, no-secret-leak e cloud
  opt-in ganham casos novos a cada feature.
- **i18n preparada**: strings amigáveis centralizadas (pt-BR primeiro; en
  depois de v1.0).
- **Performance**: startup da CLI <150 ms sem imports pesados (lazy imports já
  são padrão — manter com teste de tempo).
- **Docs vivas**: cada versão atualiza CHANGELOG + docs afetadas na mesma PR.

## Ordem e dependências

```
v0.12 (distribuição) ──► v0.13 (arquivos/voz) ──► v0.14 (memória)
                                   │
                                   ▼
                          v0.15 (skills SDK) ──► v0.16 (rotinas)
                                                      │
                v0.17 (painel) ◄──────────────────────┘
                     │
                     ▼
                v0.18 (cognição) ──► v1.0 (consolidação)
```

v0.12 vem primeiro porque cada melhoria seguinte só importa se pessoas
conseguirem instalar. v0.13/0.14 entregam valor diário (arquivos + memória).
v0.15/0.16 criam ecossistema e hábito. v0.17 remove a barreira do terminal.
v0.18/1.0 consolidam a liderança técnica.

## Como executar cada fase

Abrir missão com o template `implementation-loop-100`, sempre com:
critérios de aceite verificáveis, `pytest` 100% + `ruff` limpo, smoke real,
regressões de segurança, CHANGELOG/docs atualizados e relatório final em
`docs/missions/NOMOS_V0XX_FINAL_REPORT.md` com STATUS_FINAL evidenciado.
