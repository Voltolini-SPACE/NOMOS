# NOMOS

[![CI](https://github.com/Voltolini-SPACE/NOMOS/actions/workflows/ci.yml/badge.svg)](https://github.com/Voltolini-SPACE/NOMOS/actions/workflows/ci.yml)

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

Superfícies disponíveis (ambas em dry-run, chamando só o orquestrador
simulado):

```bash
nomos conselho simular "seu texto"     # CLI
/conselho simular seu texto            # dentro do chat
```

Garantias atuais (todas verificadas por teste, não por convenção):

- **Execução de motor real:** desligada — trava literal
  `REAL_LOCAL_ENGINE_EXECUTION_ENABLED = False`, sem API para ativar.
- **CLI e chat:** só o subcomando `simular` roda (dry-run); `conselho`/
  `/conselho` sem subcomando e os demais (`perguntar`, `revisar`, `status`,
  `modos`, `explicar`, `diagnostico`) continuam **desabilitados/fail-closed**.
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

Release candidate (v1.3.0rc4, **pre-release**). Suíte com 884 testes cobrindo
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
