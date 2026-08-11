"""NOMOS adapters.git — Git de LEITURA, tipado por operação (C1).

Esta é a primeira capacidade do NOMOS que executa processo externo depois que
`script-rodar` genérico foi retirado. Ela existe para provar uma tese: processo
externo pode existir sem devolver ao plano o poder de escolher executável,
argv, shell, cwd ou ambiente.

    script-rodar (removido)      git-status (aqui)
    plano escolhe argv[0]        runtime resolve o binário
    plano escolhe argv[1:]       runtime monta o argv INTEIRO
    plano escolhe cwd            cwd = repo validado contra o escopo
    ambiente herdado             ambiente mínimo, construído deliberadamente

O plano fornece DADOS tipados — `repo`, `ref`, `limite` — e nada mais. Nenhum
deles chega ao `argv` sem passar por gramática.

## Por que recusar `ref` que comece com `-` não é paranoia

`git log --format=x` e `git log -1` são opções; `git log v1.0` é uma ref. Se
uma "ref" começar com `-`, o Git a lê como opção — e opções do Git executam
código: `--upload-pack=`, `-c core.pager=`, `-c diff.external=`. O separador
`--` ajuda, mas a interpretação de opções varia por subcomando e por posição,
então não me apoio só nele: `-` na primeira posição é recusa, sempre.

## Por que o ambiente é construído, não herdado

O Git lê MUITA configuração do ambiente, e várias entradas executam programa:

    GIT_EXTERNAL_DIFF   roda um binário para cada diff
    GIT_PAGER / PAGER   roda um binário com a saída
    GIT_EDITOR          roda um editor
    GIT_SSH_COMMAND     roda um comando para rede
    GIT_CONFIG_*        injeta configuração arbitrária, inclusive as de cima
    GIT_EXEC_PATH       troca de onde vêm os próprios subcomandos

Herdar o ambiente do host faria a autoridade do processo depender de quem
exportou o quê — inclusive de um `~/.gitconfig` que o NOMOS não controla. O
ambiente é montado do zero.

## E a configuração DENTRO do repositório?

Um repositório pode trazer `.git/config` com `core.pager`, `diff.external` e
aliases. Por isso cada comando leva `--no-ext-diff`, `--no-textconv` e formato
FIXO, e o pager é desligado por ambiente. O teste adversarial monta um repo
hostil com essas chaves e prova que nenhuma delas executa.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from nomos.adapters import supervisor
from nomos.adapters.caminho import resolver
from nomos.adapters.contrato import (
    Adapter, CapabilityContext, CapabilityRequest, CapabilityResult,
    ErroInvalido, ErroLimite, ErroNaoEncontrado,
)
from nomos.adapters.estrito import inteiro_estrito, texto_estrito

# TRÊS operações, todas OBJECT-ONLY: leem apenas objetos já commitados.
#
# `git-status` e `git-diff` contra working tree foram REMOVIDOS depois que o
# teste do repositório hostil provou que eles executam código do próprio repo.
# Não é falha de flag: o Git roda `filter.<driver>.clean` (via .gitattributes)
# para decidir se um arquivo do working tree está modificado — o filtro É o
# mecanismo de comparação, e desligá-lo mudaria o resultado em vez de proteger.
#
# Ler repositório desconhecido só é seguro quando não se toca o working tree.
CAPACIDADES = ("git-diff", "git-log", "git-show")

TIMEOUT_S = 30.0
LIMITE_SAIDA = 1 * 1024 * 1024          # 1 MB de stdout
LIMITE_LOG = 200                        # commits por `git-log`

# Gramática de ref. Deliberadamente restritiva: cobre nome de branch, tag, SHA,
# `HEAD`, `HEAD~3`, `main@{u}` não entra. O que ela NÃO permite é mais
# importante que o que permite — nada de espaço, `-`, `..` no início, NUL,
# metacaractere de shell (que não seria interpretado, mas denuncia intenção).
_REF_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/~^-]{0,199}$")
_REF_PROIBIDO = re.compile(r"(^-)|(\.\.\.)|(@\{)|(\s)|([\x00-\x1f;&|`$(){}\[\]<>*?!\\'\"])")

# Formato FIXO. O plano nunca escolhe `--format`, porque `--format` aceita
# `%(...)` com expansões que dependem de configuração do repositório.
_FORMATO_LOG = "%H%x1f%an%x1f%aI%x1f%s"
_FORMATO_SHOW = "%H%x1f%an%x1f%aI%x1f%s%x1e"

# Configuração do REPOSITÓRIO que executa programa, neutralizada na linha de
# comando (`-c` tem precedência sobre `.git/config`).
#
# O teste adversarial encontrou `core.fsmonitor`: o Git o invoca no refresh do
# índice de `status` e `diff`, e nem `--no-ext-diff`, nem `--no-textconv`, nem
# o ambiente o alcançam — a chave vem de dentro do repo. Um `git clone` traz o
# `.git/config` de quem o produziu, então ler repositório desconhecido
# executaria código dele.
#
# A lista é positiva e explícita. Preferi enumerar as chaves que executam a
# tentar adivinhar um padrão: `core.*` tem dezenas de chaves inócuas, e uma
# regra ampla demais quebraria repositório legítimo sem cobrir mais nada.
#
# HONESTIDADE SOBRE O ESTADO ATUAL: para as TRÊS operações object-only que o
# C1 fechou, esta lista é PROVADAMENTE desnecessária. O experimento de
# equivalência montou o repo mais hostil possível (alias, pager, external
# diff, fsmonitor, filters clean/smudge, textconv, custom diff driver,
# include.path, hook post-checkout, .gitattributes ligando os filtros) e
# comparou o adapter com e sem estas linhas: canário nunca disparou e a saída
# foi byte-idêntica nas três. As chaves aqui só são consultadas ao avaliar
# conteúdo do WORKING TREE — que é justamente o que saiu do C1.
#
# Fica como defesa em profundidade, e volta a ser necessária na primeira
# capacidade que tocar working tree (C1b) ou índice (C2, `git-add`). Manter é
# barato; removê-la agora significaria reescrevê-la sob pressão depois.
_NEUTRALIZAR = [
    "-c", "core.fsmonitor=false",       # roda binário no refresh do índice
    "-c", "core.pager=cat",
    "-c", "core.editor=true",
    "-c", "core.hooksPath=/dev/null",   # nenhum hook do repo
    "-c", "core.sshCommand=true",
    "-c", "core.askPass=",
    "-c", "credential.helper=",
    "-c", "diff.external=",
    "-c", "uploadpack.packObjectsHook=",
    "-c", "protocol.ext.allow=never",   # protocolo ext:: executa comando
]


def ref_valida(bruta: str, nome: str = "ref") -> str:
    """Ref sintaticamente segura, ou `ErroInvalido`.

    A checagem de `-` no início vem ANTES da gramática positiva porque é a que
    separa "dado" de "opção": uma ref que começa com `-` é lida pelo Git como
    flag, e flags do Git executam programa.
    """
    texto = texto_estrito(bruta, nome, obrigatorio=True, maximo=200)
    if _REF_PROIBIDO.search(texto):
        raise ErroInvalido(
            f"'{nome}' inválida: {texto!r}. Ref não pode começar com '-' (o "
            "Git a leria como OPÇÃO, e opções do Git executam programa), nem "
            "conter espaço, controle ou metacaractere")
    if not _REF_OK.match(texto):
        raise ErroInvalido(f"'{nome}' fora da gramática permitida: {texto!r}")
    return texto


def ambiente_minimo() -> dict[str, str]:
    """Ambiente CONSTRUÍDO, nunca herdado.

    Cada entrada aqui é uma decisão. O que não está nesta lista não existe para
    o processo — inclusive `GIT_CONFIG_*`, `GIT_EXEC_PATH`, `GIT_SSH_COMMAND`,
    `PAGER` e `HOME` (que traria `~/.gitconfig` do usuário).
    """
    return {
        # PATH mínimo só para o Git achar os próprios helpers de sistema
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        # sem HOME não há ~/.gitconfig; sem XDG não há config do usuário
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        # nada de paginador, editor ou diff externo
        "GIT_PAGER": "cat",
        "PAGER": "cat",
        "GIT_EXTERNAL_DIFF": "",
        "GIT_EDITOR": "true",
        "GIT_TERMINAL_PROMPT": "0",       # nunca perguntar credencial
        "GIT_ASKPASS": "",
        "SSH_ASKPASS": "",
        "GIT_OPTIONAL_LOCKS": "0",        # leitura não escreve índice
        "GIT_FLUSH": "1",
    }


def executaveis_de_git() -> tuple[str, ...]:
    """Os binários que uma operação Git REALMENTE executa neste host.

    São dois: `/usr/bin/git` é o shim do xcrun, que delega ao Git de dentro do
    Xcode. Ambos precisam de literal próprio.

    O que NÃO precisa de literal, e é contraintuitivo: `git-receive-pack` e
    `git-upload-pack`. Medido neste host — os três compartilham o MESMO inode
    (1152921500312567503, hardlink), e o `git-receive-pack` do Xcode é symlink
    para `../../bin/git`. O sandbox casa o caminho REAL, então dois literais já
    cobrem os helpers.

    Derivado em runtime: fixar o caminho do Xcode quebraria tudo depois de um
    `xcode-select -s`, e cair para `process-exec` amplo seria trocar a
    fronteira por conveniência — por isso é RECUSA.
    """
    dev = os.path.realpath("/var/select/developer_dir")
    xcode_git = os.path.join(dev, "usr", "bin", "git")
    if not os.path.exists(xcode_git):
        raise supervisor.ErroSeguranca(
            f"git da toolchain não resolve ({xcode_git}) — recuso em vez de "
            "liberar process-exec amplo")
    return ("/usr/bin/git", xcode_git)


def diretorio_git(repo: Path | str) -> tuple[str, str]:
    """`(git_dir, common_dir)` canônicos, SEM executar git.

    Não uso `git rev-parse --absolute-git-dir` de propósito: resolver o
    confinamento exigiria uma execução de git, que por sua vez exige um
    confinamento. Além do ciclo, seria um `subprocess` fora do supervisor — o
    teste estrutural do C2c proíbe.

    O formato é documentado e estável: `.git` é diretório no caso comum e um
    ARQUIVO com `gitdir: <caminho>` em worktree ligada ou submódulo. Concatenar
    `<repo>/.git` cegamente daria um caminho que não existe nesses dois casos, e
    a política sairia apontando para o lugar errado.
    """
    base = Path(supervisor.existente(repo))
    ponto = base / ".git"
    if ponto.is_dir():
        git_dir = supervisor.existente(ponto)
    elif ponto.is_file():
        texto = ponto.read_text("utf-8", "replace").strip()
        if not texto.startswith("gitdir:"):
            raise ErroInvalido(f"arquivo .git ilegível em {base}")
        alvo = texto.split(":", 1)[1].strip()
        git_dir = supervisor.existente(
            alvo if os.path.isabs(alvo) else str(base / alvo))
    else:
        raise ErroInvalido(f"não é repositório git: {base}")

    # Em worktree ligada o estado compartilhado (objects, refs do repo
    # principal) vive no common dir, não no git dir da worktree.
    comum = Path(git_dir) / "commondir"
    if comum.is_file():
        bruto = comum.read_text("utf-8", "replace").strip()
        common = supervisor.existente(
            bruto if os.path.isabs(bruto) else str(Path(git_dir) / bruto))
    else:
        common = git_dir
    return git_dir, common


def confinamento_de_leitura(repo: Path | str) -> supervisor.Confinamento:
    """Capacidades object-only: NENHUMA escrita no repositório.

    Medido: `git-log`, `git-show` e `git-diff(refA, refB)` produzem saída
    byte-idêntica à execução sem sandbox sem um único allow de escrita. O
    `/dev/null` que o perfil sempre emite continua necessário porque
    `GIT_CONFIG_GLOBAL=/dev/null` é aberto em leitura E escrita.

    É a maior redução barata desta fase: uma capacidade de leitura que
    fisicamente não consegue escrever, em vez de uma que promete não escrever.
    """
    git_dir, comum = diretorio_git(repo)
    raizes = (supervisor.existente(repo), git_dir)
    if comum != git_dir:
        raizes += (comum,)
    return supervisor.Confinamento(escrita=(), declara_sem_escrita=True,
                                   leitura=raizes,
                                   exec_permitido=executaveis_de_git())


def confinamento_de_repo(repo: Path | str,
                         rede: bool = False) -> supervisor.Confinamento:
    """Autoridade de filesystem de UMA execução Git: o repositório e mais nada.

    O caminho é canonicalizado ANTES de virar política — não depois, não pelo
    caller. `/tmp/x` e `/private/tmp/x` são o mesmo diretório, mas só o segundo
    casa com o que o Git usa; um perfil escrito com o primeiro nega a operação
    legítima e parece falta de permissão.

    A escrita para no DIRETÓRIO GIT — a working tree fica fora.

    A hipótese foi medida e confirmada: `git add` e `git commit` não escrevem
    nada no working tree, só no git dir. O ganho não é teórico. Com o repo
    inteiro liberado, um `filter.clean` hostil SOBRESCREVEU um arquivo do
    projeto durante o `git add`, com rc=0 e sem nenhum sinal. Com a escrita
    limitada ao git dir, o mesmo filtro leva "Operation not permitted", o
    arquivo do projeto fica intacto e o `add` continua funcionando.

    Descer ABAIXO do git dir foi TENTADO E REFUTADO por medição. A allowlist
    óbvia (index, objects, refs, logs, COMMIT_EDITMSG) falha por `HEAD.lock`,
    que é lock transitório e não aparece em inventário de mtime; e mesmo
    corrigida, todo commit passa a emitir `cannot lock ref 'AUTO_MERGE'` com
    rc=0 — degradação silenciosa, que é justamente o modo de falha que esta
    série vem eliminando. O git dir é o ponto estável: o contrato público "todo
    estado mutável do repositório vive dentro do diretório Git" sobrevive a
    mudanças de layout interno (packfiles, commit-graph, reftable).
    """
    git_dir, common = diretorio_git(repo)
    raizes = (git_dir,) if common == git_dir else (git_dir, common)
    # A6: o git dir é gravável, MENOS os três lugares de onde o repositório
    # consegue fazer código sobreviver à operação. `git add`/`commit` não
    # precisam escrever em nenhum deles — medido, `quebras=[]`.
    #
    #   hooks/   programa que o Git executa em eventos futuros
    #   config   `filter.*.clean`, `core.fsmonitor`, aliases `!`
    #   info/    `info/attributes` liga arquivo a filtro, como .gitattributes
    #
    # Sem isto, um filtro contido nesta execução ainda podia INSTALAR o
    # próximo: a contenção valeria uma vez só.
    proibidos = tuple(f"{raiz}/{nome}" for raiz in raizes
                      for nome in ("hooks", "info", "config"))
    return supervisor.Confinamento(escrita=raizes, rede=rede,
                                   negacao_de_escrita=proibidos,
                                   exec_permitido=executaveis_de_git())


class GitAdapter(Adapter):
    """Quatro operações de LEITURA. Nenhuma delas muta, nenhuma usa rede."""

    capacidades = CAPACIDADES

    def __init__(self, binario: str | None = None):
        # O binário é resolvido pelo RUNTIME, não pelo plano. Guardado no
        # adapter, não em parâmetro — não há por onde um plano trocá-lo.
        self._git = binario or "/usr/bin/git"

    def executar(self, pedido: CapabilityRequest,
                 ctx: CapabilityContext) -> CapabilityResult:
        self._coerente(pedido, ctx)
        repo = self._repo(pedido, ctx)
        argv = self._argv(pedido, repo)
        saida, r = self._rodar(argv, repo, ctx)
        self._auditar(ctx, f"git.{pedido.capacidade[4:]}",
                      alvo=supervisor.canonicalizar(repo), bytes=len(saida),
                      sandbox=True, rede=False,
                      classificacao=r.classificacao,
                      morto_por_timeout=r.morto_por_timeout)
        return CapabilityResult.sucesso(saida, efeito_aplicado=False)

    # ------------------------------------------------------------- entradas

    def _repo(self, pedido, ctx) -> Path:
        """O repositório, confinado pelo MESMO escopo do filesystem."""
        bruto = texto_estrito(pedido.alvo, "alvo", obrigatorio=True)
        repo = resolver(bruto, ctx.raizes)
        if not repo.is_dir():
            raise ErroNaoEncontrado(f"não é diretório: {repo}")
        if not (repo / ".git").exists():
            raise ErroInvalido(f"não é repositório git: {repo}")
        return repo

    def _argv(self, pedido, repo: Path) -> list[str]:
        """O argv INTEIRO é montado aqui. O plano não contribui com nenhum
        elemento — só com os dados que preenchem posições fixas."""
        nome = pedido.capacidade
        base = [self._git, "-C", str(repo), "--no-pager", *_NEUTRALIZAR]
        if nome == "git-diff":
            # AS DUAS refs são OBRIGATÓRIAS. Sem isso, `git diff` sem
            # argumentos compara contra o WORKING TREE, e é justamente esse
            # caminho que executa o filtro do repositório. Um default que
            # muda a semântica para working tree seria o furo de volta,
            # disfarçado de conveniência.
            a = ref_valida(pedido.arg("ref_a"), "ref_a")
            b = ref_valida(pedido.arg("ref_b"), "ref_b")
            return base + ["diff", "--no-ext-diff", "--no-textconv",
                           a, b, "--"]
        if nome == "git-log":
            limite = inteiro_estrito(pedido.arg("limite"), "limite",
                                     padrao=20, minimo=1, maximo=LIMITE_LOG)
            argv = base + ["log", "--no-ext-diff", f"--format={_FORMATO_LOG}",
                           "-n", str(limite)]
            ref = pedido.arg("ref")
            if ref:
                argv.append(ref_valida(ref, "ref"))
            return argv + ["--"]
        if nome == "git-show":
            ref = ref_valida(pedido.arg("ref") or "HEAD", "ref")
            return base + ["show", "--no-ext-diff", "--no-textconv",
                           f"--format={_FORMATO_SHOW}", "--stat", ref, "--"]
        raise ErroInvalido(f"operação git desconhecida: {nome}")

    # ------------------------------------------------------------- execução

    def _rodar(self, argv: list[str], repo: Path,
               ctx) -> tuple[str, supervisor.Resultado]:
        prazo = min(TIMEOUT_S, ctx.restante() or TIMEOUT_S)
        p = supervisor.executar(
            argv, cwd=repo, env=ambiente_minimo(), prazo=prazo,
            confinamento=confinamento_de_leitura(repo))
        if p.morto_por_timeout:
            raise ErroLimite(f"git excedeu {prazo:.1f}s")
        if len(p.stdout) > LIMITE_SAIDA:
            raise ErroLimite(f"saída do git acima de {LIMITE_SAIDA} bytes")
        if p.returncode != 0:
            erro = p.stderr.decode("utf-8", "replace")[:400]
            raise ErroInvalido(f"git falhou (rc={p.returncode}): {erro}")
        supervisor.conferir_saida(p.stderr, "git")
        return p.stdout.decode("utf-8", "replace"), p
