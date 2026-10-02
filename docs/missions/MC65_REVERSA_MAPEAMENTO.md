# MC65 — NOMOS Reversa: mapeamento e engenharia reversa de ferramentas de terceiros

## 1. Status

```
STATUS_FINAL=PASS_MC65_REVERSA_MAPEAMENTO
TESTES=31 passed
RUFF=All checks passed
BRANCH=mc65-reversa-mapeamento
PUSH=nao (decisao humana)
```

## 2. Motivação (regra do proprietário, 02/10/2026)

> «validar sempre toda e qualquer skill ou sistema git», «construir ferramenta
> própria nossa para engenharia reversa», «dar preferência sempre por mapear a
> ferramenta desejada, aprimorar o que for necessário e construir a própria de
> preferência como componente nomos».

A regra está codificada no `AGENTS.md` global (`VOLTOLINI_VALIDACAO_OBRIGATORIA`).
A MC65 é a **ferramenta nossa** que falta para cumpri-la: até aqui a validação
era manual, feita no chat, sem evidência durável e sem contrato testável.

## 3. O que foi construído

Um componente do NOMOS que **mapeia** uma ferramenta de terceiros sem executá-la.

| Camada | Caminho | Papel |
|---|---|---|
| Componente | `src/nomos/reversa/mapa.py` | Núcleo: varredura, catálogo de padrões, risco, blueprint |
| API | `src/nomos/reversa/__init__.py` | `mapear`, `para_dict`, `relatorio`, `Mapa`, `Achado` |
| CLI de agente | `tools/nomos_reversa.py` | Agente autônomo (padrão MC29), determinístico |
| CLI do produto | `src/nomos/cli.py` → `nomos reversa` | Comando amigável no produto |
| Testes | `tests/test_mc65_reversa.py` | 31 testes de contrato |

### O que o mapa responde

Reproduz, com contrato testável, as seis perguntas da regra de validação:
**origem** (organização/remote/branch/HEAD), **integridade** (inventário e hashes
do material), **autoria** (assinaturas por skill), **superfície** (execução,
rede, credenciais), **permissões** (manifesto) e **licença** — e termina num
**blueprint de reimplementação**, que é a razão de existir: a preferência é
construir o nosso.

### Categorias de achado

`execucao` · `rede` · `credencial` · `injecao` · `empacotamento` · `git` · `skill`

## 4. Contrato de segurança (o que os testes provam)

1. **O alvo nunca é executado.** Fixture com script que criaria um arquivo
   sentinela: o arquivo não existe depois do mapa. `executed_target is False`.
2. **Nada é escrito dentro do alvo.** Retrato da árvore antes/depois é idêntico;
   o repositório real não fica sujo (`git status --short` igual antes e depois).
3. **Links simbólicos não são seguidos** na varredura, e um alvo que é link é
   recusado explicitamente.
4. **git só por allowlist de leitura** (`rev-parse`, `remote`, `log`, `describe`,
   `symbolic-ref`), com `core.hooksPath` e `core.fsmonitor` neutralizados por
   `-c`: um repositório hostil não ganha execução só por ser mapeado.
5. **Hook git é tratado como código**, não como configuração — inclusive
   `hooksPath` customizado e filtros `clean`/`smudge`.
6. **Skill sem assinatura é achado registrado**, nunca silêncio.
7. **A CLI não expõe nenhuma flag de mutação ou publicação** (`--push`,
   `--commit`, `--apply`, `--install`, `--exec`, `--run`): por construção, o
   agente é incapaz de mutar o alvo.
8. **Saída determinística** — mesma entrada, mesmo JSON (gate de CI).
9. **Fail-closed**: alvo inexistente, manifesto ilegível e alvo-link viram risco
   alto, não exceção silenciosa.

## 5. Dogfooding — alvos reais

### 5.1 Skills NVIDIA instaladas (`~/.agents/skills`)

O mapeador **reproduziu de forma independente** a auditoria manual feita antes:

```
- nemo-relay-instrument-context-isolation    assinatura=skill.oms.sig
- nemoclaw-user-guide                        assinatura=AUSENTE
achado: [medio] skill-sem-assinatura -> nemoclaw-user-guide
```

A primeira versão tinha uma **limitação real** que o dogfooding expôs: olhava só
a raiz do alvo e por isso perdia a assinatura de todas as skills menos uma. A
correção (`_raizes_de_skill`) tem teste de regressão dedicado.

### 5.2 Marketplace de terceiros (`HKUDS/CLI-Anything`, 60 MB, 1.869 arquivos)

```
risco: alto
execucao=3  rede=531  credencial=83  injecao=0  empacotamento=0  git=0  skill=151
```

Achados altos (amostra):

| Regra | Local | Trecho |
|---|---|---|
| `pipe-para-shell` | `public_registry.json:312` | `curl -s https://jimeng.jianying.com/cli \| bash` |
| `pipe-para-shell` | `registry.json:1255` | `curl -fsSL https://raw.githubusercontent.com/…/install.sh \| bash` |
| `pipe-para-shell` | `public_registry.json:220` | nota de instalação com `curl … \| bash` |

Sem hooks git ativos (`git=0`), mas com **151 skills sem assinatura** e comandos
de instalação que baixam e executam código de domínio de terceiro. É exatamente
o risco que a regra do proprietário manda mapear antes de adotar.

Evidências: `~/Documents/Voltolini/mesa-ia/validacoes/2026-10-02/evidence/reversa-cli-anything/`.

### 5.3 Licença — o falso negativo que a medição revelou (02/10, sessão de validação)

A primeira versão olhava **um** arquivo de licença. Medido contra os alvos reais
da auditoria de dependências do dia:

| Alvo | Antes | Depois |
|---|---|---|
| `vectorbt` (LICENSE.md = Apache + Commons Clause; `docs/LICENSE.md` = AGPL) | `Apache-2.0`, risco **médio**, **zero** achados de licença | 4 achados **altos**: cláusula restritiva, copyleft forte, uso não comercial e **licença da documentação divergente** |
| `freqtrade` (GPL-3.0-only) | `GPL` (sem distinguir `only` de `or-later`) | `GPL-3.0-only` + copyleft forte |
| `NOMOS` (MIT) | MIT | MIT, sem achado (sem falso positivo) |

O caso do `vectorbt` é o exemplo que justifica a regra: a documentação dele é
AGPL, então "não posso embutir, clono pela doc" seria **pior** que a rota
proibida. Um mapeador que só lê o `LICENSE` da raiz não vê isso.

Regras agora cobertas: `licenca-ausente`, `licenca-clausula-restritiva`,
`licenca-uso-nao-comercial`, `licenca-copyleft-forte`, `licenca-copyleft-fraca`,
`licenca-da-documentacao-divergente`, `licenca-conflitante`. A classificação
entende expressões SPDX do `License-Expression` (PEP 639): em `A OR B` vale a
menos restritiva; em `A AND B`, a mais restritiva manda.

**Gate de licença no SBOM:** `python tools/make_sbom.py <out> --gate-licenca`
declara a licença de cada componente no CycloneDX e **reprova** (saída 3) quem
tenha copyleft forte ou cláusula restritiva. Usa a **mesma**
`classificar_licenca` do mapeador — uma regra só.

## 6. Como usar

```bash
nomos reversa <alvo>                 # relatório legível
nomos reversa <alvo> --json          # contrato estável para CI
nomos reversa <alvo> --saida DIR     # grava mapa.md + mapa.json (única escrita)

python tools/nomos_reversa.py --mapa <alvo> --json   # agente autônomo
```

## 7. Arquivos criados/alterados

Criados:
- `src/nomos/reversa/__init__.py`
- `src/nomos/reversa/mapa.py`
- `tools/nomos_reversa.py`
- `tests/test_mc65_reversa.py`
- `docs/missions/MC65_REVERSA_MAPEAMENTO.md`

Alterados:
- `src/nomos/cli.py` — `cmd_reversa` + subcomando `reversa`
- `tools/make_sbom.py` — licença por componente no SBOM + `--gate-licenca`
- `CHANGELOG.md` — seção `[Unreleased]`

**Não tocado:** `site/index.html` (modificação de trabalho concorrente,
preservada intacta — a menção ao `reversa` na página é a pendência MC33 abaixo).

## 8. Pendências explícitas

1. **Push é decisão humana** (regra inviolável §2 do `CLAUDE.md`). O trabalho
   fica na branch `mc65-reversa-mapeamento`, commitado e pronto para revisão.
2. **REGRA MC33** (o site sempre reflete o produto): o site ainda **não**
   menciona `nomos reversa`. Pendência aberta, não um fato consumado.
3. **REGRA MC35** (dogfooding): a ferramenta já está no produto (não só no Mac),
   mas a entrada no README de capacidades ficou pendente de decisão.
4. **Sincronização Mac ↔ Spark** das branches locais não foi executada.
5. **Engenharia reversa de binário** não é escopo desta missão: o mapa descreve
   o material distribuído. Se um dia for preciso, será missão própria, com
   ambiente isolado e autorização — as ferramentas não estão instaladas
   (nem no Mac, nem na Spark).
