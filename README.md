# NOMOS

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
- ✋ **Pede licença** — toda ação sensível passa por uma aprovação sua.
- 🎯 **Nunca finge** — sem cérebro conectado, avisa; jamais inventa resposta.
- 🎨 **Do seu jeito** — nome do agente, personalidade e cores personalizáveis.

## Instalação rápida

Requer **Python 3.10+**.

```bash
pip install nomos-0.10.0-py3-none-any.whl
nomos            # abre o assistente na primeira vez
```

Instaladores de um clique para **Mac, Windows e Linux** e um manual ilustrado
estão na pasta de release. Depois de instalar, é só rodar `nomos`.

## Comandos essenciais

| Comando | O que faz |
|---|---|
| `nomos` | abre o seu agente (ou o assistente, na 1ª vez) |
| `nomos doutor` | check-up: o que está pronto e o próximo passo |
| `nomos cerebro baixar` | baixa o cérebro leve (uma vez, ~400 MB) |
| `nomos local status` | mostra o cadeado que mantém tudo local |
| `nomos chaves` | guarda chaves com segurança, sem digitar no chat |

Dentro da conversa: `/ajuda`, `/cerebro`, `/chaves`, `/motores`, `/tema`,
`/local`, `/doutor`, `/sair`.

## Como funciona

O NOMOS tem um kernel de governança (política fail-closed, gate de aprovação,
cofre Argon2id, auditoria com cadeia de hash, cadeado de localidade) e uma
camada de cognição (cérebro embutido via `llama.cpp`, memória local SQLite,
roteador local-first). Tudo em Python puro, multiplataforma.

## Desenvolvimento

```bash
pip install -e .
python -m pytest -q          # 246 testes
ruff check src tests         # lint
```

## Licença

[MIT](LICENSE) © Se7enpay
