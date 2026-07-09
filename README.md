# NOMOS

[![CI](https://github.com/Voltolini-SPACE/NOMOS/actions/workflows/ci.yml/badge.svg)](https://github.com/Voltolini-SPACE/NOMOS/actions/workflows/ci.yml)
[![Python 3.10 to 3.13](https://img.shields.io/badge/python-3.10_to_3.13-5AF78E?logo=python&logoColor=white)](https://github.com/Voltolini-SPACE/NOMOS/blob/main/pyproject.toml)
[![License MIT](https://img.shields.io/badge/license-MIT-5AF78E)](https://github.com/Voltolini-SPACE/NOMOS/blob/main/LICENSE)
[![local-first](https://img.shields.io/badge/local--first-100%25-5AF78E)](https://github.com/Voltolini-SPACE/NOMOS/blob/main/docs/PRIVACIDADE.md)

**Seu agente. Sua máquina. Suas regras.** — *local por lei.*

NOMOS é um agente pessoal de IA que roda **100% no seu computador**. Cérebro,
memória, chaves e registros ficam na sua máquina. A nuvem é opcional e só
funciona se você "plugar" de propósito. Leve, sem exigir super-PC, e feito
para iniciantes.

```
███╗   ██╗ ██████╗ ███╗   ███╗ ██████╗ ███████╗
████╗  ██║██╔═══██╗████╗ ████║██╔═══██╗██╔════╝
██╔██╗ ██║██║   ██║██╔████╔██║██║   ██║███████╗
██║╚██╗██║██║   ██║██║╚██╔╝██║██║   ██║╚════██║
██║ ╚████║╚██████╔╝██║ ╚═╝ ██║╚██████╔╝███████║
╚═╝  ╚═══╝ ╚═════╝ ╚═╝     ╚═╝ ╚═════╝ ╚══════╝
```

## Por que NOMOS

- 🔒 **Local por lei** — por padrão, nada sai da sua máquina. A própria política
  bloqueia qualquer saída para a internet até você permitir.
- 🧠 **Cérebro leve embutido** — não precisa de Ollama nem GPU. Baixa um modelo
  pequeno (a partir de ~400 MB) que roda em qualquer laptop, uma vez só.
- ✋ **Pede licença** — toda ação sensível passa por uma aprovação sua; em
  scripts/CI a resposta é sempre "não" (fail-closed, sem flag de bypass).
- 🎯 **Nunca finge** — sem cérebro conectado, avisa; jamais inventa resposta.
- 🧩 **Skills governadas** — habilidades instaláveis que só fazem o que
  declaram, com risco visível e aprovação humana.
- 🚦 **Roteador automático** — escolhe o melhor motor para cada tarefa,
  local primeiro, sem você precisar entender de modelos.
- 🎨 **Do seu jeito** — nome do agente, personalidade e cores personalizáveis.

## Capacidades

<!-- NOMOS:CAPS:START -->

| Capacidade | O que faz | Como |
|---|---|---|
| Local por lei | Por padrão nada sai da máquina; a política bloqueia egress até você permitir. | — |
| Pede licença (A0–A6) | Toda ação sensível é aprovada por você; em scripts/CI a resposta é sempre não. | — |
| Nunca finge | Sem cérebro pronto, avisa; jamais inventa resposta ou dado. | — |
| Cérebro leve embutido | Modelo pequeno (a partir de ~400 MB) que roda sem GPU nem Ollama. | `nomos cerebro` |
| Roteador automático | Escolhe o melhor motor por tarefa — local primeiro. | `nomos motores` |
| Memória local | SQLite na sua máquina com busca full-text; você revisa o que vira permanente. | `nomos memoria` |
| Memória que atravessa sessões | Motor auditável: dry-run por padrão, hash de integridade, recusa segredos e PII. | `python -m nomos.memory.cli` |
| Mosaic — telas ao vivo no painel | Várias telas isoladas em mosaico dentro do painel, vistoriadas pelo agente. | `python -m nomos.mosaic.cli` |
| Conversas com retenção | Abra, busque, fixe, exporte e esqueça conversas — retenção sob seu controle. | `nomos conversas` |
| Missões que fazem | Plano legível → uma aprovação → execução passo a passo → evidência; um comando desfaz. | `nomos missao` |
| Fila de aprovações | Ação sensível passa por fila com token de uso único; no terminal ou no painel. | `nomos approvals` |
| Motor Council | Vários motores respondem, revisam às cegas e um árbitro converge — fail-closed. | `nomos conselho` |
| Cofre e backup | Chaves com senha-mestra; seu NOMOS inteiro num arquivo cifrado. | `nomos chaves` |
| Skills governadas | Habilidades instaláveis e assinadas que só fazem o que declaram. | `nomos skills` |
| Agentes com escopo | Agentes oficiais e próprios, com ferramentas, motores e risco máximo definidos. | `nomos agentes` |
| Auditoria com âncora | Trilha com âncora HMAC — evidência que não muda em silêncio. | `nomos logs` |
| Painel web local + chat | Status, motores, evidências, política viva e chat local — só 127.0.0.1. | `nomos painel` |
| Conectores MCP oficiais | Telegram, WhatsApp, e-mail (SMTP/IMAP), Slack, Signal e calendário .ics — governados (A3/A0). | `nomos mcp` |
| Rotinas e briefing 2.0 | Resumo do dia + o que chegou, entregue no seu canal, sempre com seu OK. | `nomos rotinas` |
| Atualização com licença | Checa versão nova e propõe — nunca atualiza sozinho. | `nomos atualizar` |
| Evidências verificáveis | Cada missão gera pacote com relatório, manifesto e SHA-256, auditável offline. | `nomos evidencia` |
| Botão de pânico | Um comando corta tudo: revoga consentimentos e tranca. | `nomos panic` |
| Doutor | Check-up honesto do que está pronto e o próximo passo. | `nomos doutor` |
<!-- NOMOS:CAPS:END -->

## Instalação (estado atual)

Requer **Python 3.10+**. Instalação a partir do código:

```bash
git clone https://github.com/Voltolini-SPACE/NOMOS
cd NOMOS
pip install .
nomos            # 1ª vez: assistente guiado; depois: menu principal
```

Ou pelos **instaladores de 1 clique** anexados a cada release do GitHub
(`install.sh` para Mac/Linux, `install.ps1` para Windows) — com verificação de
integridade, backup automático e rollback. Detalhes: [docs/INSTALL.md](docs/INSTALL.md).

## Comece por aqui

| Comando | O que faz |
|---|---|
| `nomos` | menu principal amigável (ou onboarding, na 1ª vez) |
| `nomos doutor` | check-up: STATUS GERAL + o próximo passo recomendado |
| `nomos cerebro baixar` | baixa o cérebro leve (uma vez; pede sua aprovação) |
| `nomos skills` | menu de habilidades: instalar, ver permissões, diagnóstico |
| `nomos motores listar` | motores por modalidade: custo, privacidade, status |
| `nomos motores recomendar texto` | o que o roteador usaria, e por quê |
| `nomos motores auto on` | roteamento automático local-first (padrão: ligado) |
| `nomos local status` | o cadeado que mantém tudo local |
| `nomos chaves` | guarda chaves com segurança, sem digitar no chat |
| `nomos arquivo <caminho>` | lê e resume um arquivo seu, tudo local (PDF com extra opcional) |
| `nomos backup criar <arquivo>` | seu NOMOS inteiro num arquivo cifrado (memórias, chaves, tudo) |
| `nomos painel` | cockpit web local (status, aprovações, chat) + **NOMOS Dash** ao vivo |
| `nomos mcp exemplos` | conectores que acompanham o NOMOS (Telegram, WhatsApp, e-mail, Signal, Slack, calendário) e como ligar |
| `nomos mcp buscar <termo>` | acha um conector embarcado por nome ou descrição (ex.: `nomos mcp buscar agenda`) — sem acento/caso |
| `nomos mcp assinatura <conector>` | verifica a **assinatura opcional de autor** (ed25519) — camada acima do SHA-256; recusa no `confiar` se estiver inválida |
| `nomos mcp doutor` | check-up dos conectores: confiança, credenciais no ambiente (só presença) e interpretador — só-leitura |
| `nomos entrada telegram` / `email` / `calendario` | lê o que chegou (mensagens) ou a sua **agenda** por um conector confiado — só leitura, governado (A3; o calendário local é A0) |
| `nomos entrada <canal> --dia` | briefing 2.0: junta "o que chegou"/"sua agenda" + "o seu dia" numa visão só |
| `nomos conselho status` / `modos` / `simular` | Motor Council: estado e modos (informativo) + simulação segura em dry-run |
| `nomos rotinas criar "Briefing" 08:00 briefing-telegram:<chat>` | briefing diário entregue no seu canal — `telegram`/`whatsapp`/`email`/`slack` (com seu OK, A3) |
| `nomos doutor --consertar` | aplica correções seguras com a sua confirmação |
| `nomos atualizar` | checa se há versão nova (com sua aprovação; **nunca** atualiza sozinho) |

Dentro da conversa: `/ajuda`, `/cerebro`, `/chaves`, `/motores`, `/tema`,
`/local`, `/doutor`, `/contexto` (transparência do que vai ao motor), `/sair`.

## O que o NOMOS nunca faz sem a sua permissão

Sair para a internet; usar motor de nuvem; usar chave do cofre; criar/alterar
arquivo; executar código; instalar skill; acessar microfone/câmera/tela.
Ações destrutivas são negadas por padrão. Detalhes e mecanismos:
[docs/PRIVACIDADE.md](docs/PRIVACIDADE.md).

## Documentação

- [Guia do iniciante](docs/USUARIO_INICIANTE.md) — sem jargão
- [Modelo de ameaças](docs/THREAT_MODEL.md) — cada garantia com o teste que a prova
- [Instalação](docs/INSTALL.md) · [Privacidade](docs/PRIVACIDADE.md)
- [Motores](docs/MOTORES.md) · [Roteador automático](docs/ROTEADOR.md)
- [Conectores sociais](docs/CONECTORES_SOCIAIS.md) — Telegram, WhatsApp, e-mail (o mapa honesto)
- [Skills](docs/SKILLS.md) · [Changelog](CHANGELOG.md)

## Como funciona

O NOMOS tem um kernel de governança (política fail-closed A0–A6, gate de
aprovação, cofre Argon2id, auditoria com cadeia de hash, cadeado de
localidade) e uma camada de cognição (cérebro embutido via `llama.cpp`,
memória local SQLite, catálogo de motores por modalidade, roteador automático
local-first e pipelines com política em cada etapa). Skills passam por
manifesto validado, checksum, assinatura ed25519 e trust store. Tudo em
Python puro, multiplataforma.

## Motor Council

O **Motor Council** — um pipeline de múltiplos motores que revisa, julga e
arbitra respostas antes de entregá-las — está disponível em modo
**dry-run / pre-release** na tag `v1.3.0rc4-motor-council-dry-run` (um
**pre-release**, não a versão "latest" do repositório). **Ainda não é
produção** e **não executa motor de verdade**.

Superfícies disponíveis hoje (nenhuma executa motor real):

```bash
nomos conselho ajuda                   # mapa dos comandos do Council
nomos conselho status                  # estado + travas (informativo)
nomos conselho modos [--avancado]      # os 4 modos (aceita --json)
nomos conselho diagnostico [--json]    # lê a trava REAL do harness, ao vivo
nomos conselho simular "seu texto"     # simulação segura (dry-run)
/conselho status                       # os mesmos, dentro do chat
/conselho modos
/conselho simular seu texto
```

Garantias atuais (todas verificadas por teste, não por convenção):

- **Execução de motor real:** desligada — trava literal
  `REAL_LOCAL_ENGINE_EXECUTION_ENABLED = False`, sem API para ativar.
- **CLI e chat:** `status` e `modos` são **informativos puros** (só imprimem
  fatos estáticos — nada de motor, prompt, rede ou disco); `simular` roda em
  **dry-run**; e `perguntar`, `revisar`, `explicar`, `diagnostico` — que
  exigiriam execução real — seguem **desabilitados/fail-closed** nas duas
  superfícies.
- **Policy/Audit/Vault reais:** não são chamados (o gate e o audit são só
  dry-run; A0–A6 simulado, `would_write_audit=false`).
- **Nuvem / rede / subprocess:** não usados por nenhum módulo do Council.
- **Persistência:** desligada no fluxo do Council.
- **Prompt / conteúdo bruto:** nunca aparece nas saídas (redação; só campos
  escalares seguros, inclusive no `--json`).
- **Modo privado / paranoico:** força `persist_allowed=false`.

Detalhes técnicos e o mapa completo das fases MC0–MC18:

- [`docs/architecture/MOTOR_COUNCIL_INDEX_v1.md`](docs/architecture/MOTOR_COUNCIL_INDEX_v1.md) — índice técnico
- [`docs/architecture/MOTOR_COUNCIL_UX_SPEC_v1.md`](docs/architecture/MOTOR_COUNCIL_UX_SPEC_v1.md) — UX de CLI/chat
- [`docs/architecture/MOTOR_COUNCIL_CHAT_DRY_RUN_SPEC_v1.md`](docs/architecture/MOTOR_COUNCIL_CHAT_DRY_RUN_SPEC_v1.md) — spec do chat dry-run

## Maturidade

Release candidate (v1.3.0rc4, **pre-release**). Suíte com mais de 1.100 testes cobrindo
segurança (fail-closed, não-vazamento de segredo, opt-in de nuvem) e UX. O
**Motor Council** está em dry-run (ver seção acima): o subcomando `simular`
roda na CLI e no chat, mas sem execução de motor real, sem nuvem e sem
persistência. API interna pode mudar; os comandos da tabela acima são
estáveis.

## Desenvolvimento

```bash
pip install -e .
python -m pytest -q          # suíte completa
ruff check src tests         # lint
```

## Licença

[MIT](LICENSE) © Se7enpay
