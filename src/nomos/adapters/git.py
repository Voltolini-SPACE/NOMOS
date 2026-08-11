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
from dataclasses import dataclass
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
        # `refs/replace/<sha>` faz o Git servir OUTRO objeto no lugar do que foi
        # pedido, e a ref é escrita pelo REPOSITÓRIO. MEDIDO: com um replace
        # plantado, `git-show <sha real>` do NOMOS devolveu ok=True com o sha
        # verdadeiro e a mensagem de outro commit — 'MENSAGEM_FORJADA_PELO_REPO'.
        # Isto falsifica a EVIDÊNCIA: o histórico é o que o NOMOS usa para
        # auditar a si mesmo, e uma auditoria que lê o objeto errado com
        # sucesso é pior que uma que falha.
        #
        # Vai no ambiente e não em `_NEUTRALIZAR` de propósito: `git-log`,
        # `git-show`, `git-diff`, `git-add`, `git-commit`, `git-tag` e
        # `git-push` herdam todos daqui, e a lista de neutralização é por
        # adapter — deixaria buracos por construção.
        "GIT_NO_REPLACE_OBJECTS": "1",
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


@dataclass(frozen=True)
class AutoridadeDeRepo:
    """A identidade do repositório RESOLVIDA E VALIDADA uma única vez.

    Existe por causa de um TOCTOU medido, com exploração real: `.git` é um
    arquivo que o REPOSITÓRIO escreve, e o fluxo o relia do disco de 4 a 6 vezes
    por operação. `conferir_git_dir` validava a PRIMEIRA leitura e devolvia a
    tupla — e os quatro chamadores DESCARTAVAM o retorno, deixando cada etapa
    seguinte (`confinamento_de_repo`, `_instantaneo_do_indice`,
    `_abrir_quarentena`, `_promover_quarentena`) resolver de novo.

    Um escritor concorrente que troca `.git` depois da checagem move o efeito
    para outro git dir. MEDIDO em `git-push`: corrida vencida 1/40 e 3/40, com o
    NOMOS reportando `ok=True` e PUBLICANDO um repositório INTEIRAMENTE FORA das
    raízes, `AWS_SECRET_ACCESS_KEY` incluído. Janela medida: 115 ms no `add`,
    90,5 ms no `push`.

    O formato do conserto importa mais que o conserto:

        resolve -> validate -> BIND AUTHORITY -> effect      (o que se faz aqui)
        resolve -> validate -> discard -> resolve again -> effect   (o defeito)

    "Conferir de novo antes de cada uso" seria mais um ponto de corrida, não
    menos: o que fecha é o efeito consumir a MESMA autoridade que foi validada,
    e não uma releitura sua.
    """
    repo: str
    git_dir: str
    common: str

    @property
    def raizes_de_escrita(self) -> tuple[str, ...]:
        return ((self.git_dir,) if self.common == self.git_dir
                else (self.git_dir, self.common))


def autoridade_de(repo: Path | str, git_dir: str, common: str) -> AutoridadeDeRepo:
    return AutoridadeDeRepo(repo=str(supervisor.existente(repo)),
                            git_dir=git_dir, common=common)


def conferir_git_dir(repo: Path | str, raizes: tuple[str, ...]) -> tuple[str, str]:
    """`(git_dir, common)` resolvidos E CONFRONTADOS com as raízes aprovadas.

    MEDIDO, e é o defeito de maior alavancagem que a bateria A2-REPO encontrou:
    `resolver()` valida o DIRETÓRIO DE TRABALHO contra as raízes, e mais nada.
    `diretorio_git()` então segue duas indireções que o REPOSITÓRIO escreve —
    `.git` como arquivo (`gitdir: <caminho>`) e `<git_dir>/commondir` — e devolve
    o destino sem ninguém conferir onde ele foi parar.

    A consequência não é teórica. `confinamento_de_repo()` usa esse git dir como
    RAIZ DE ESCRITA do sandbox. Logo:

        .git (arquivo) -> gitdir: /fora/das/raizes
        => o repositório ESCOLHEU uma raiz de escrita do NOMOS

    Reproduzido ponta a ponta: `git-add` devolveu `efeito_aplicado=True` e gravou
    o índice em `/fora/das/raizes`. É exatamente a negação da propriedade que
    A2-REPO existe para provar — `REPOSITORY_CANNOT_EXPAND_NOMOS_AUTHORITY`.

    A indireção continua SUPORTADA: worktree ligada e submódulo são legítimos e
    usam `.git` como arquivo. O que muda é que o destino passa a precisar estar
    dentro das mesmas raízes que o diretório de trabalho — quem aprovou a raiz
    aprovou o que mora nela, e nada além.

    Resolver UMA vez e passar a tupla adiante também fecha o TOCTOU: enquanto
    cada chamada relia `.git` do disco, um escritor concorrente podia trocar o
    destino entre a validação e o uso.
    """
    git_dir, common = diretorio_git(repo)
    if not raizes:
        # Sem raízes declaradas não há o que conferir, e inventar uma seria pior
        # que não ter: o chamador que não delimita escopo tem de ser corrigido,
        # não silenciosamente contido por um palpite deste módulo.
        return git_dir, common
    reais = tuple(supervisor.canonicalizar(r) for r in raizes)
    for rotulo, caminho in (("git dir", git_dir), ("common dir", common)):
        if not _dentro(caminho, reais):
            raise supervisor.ErroSeguranca(
                f"{rotulo} do repositório resolve para {caminho!r}, FORA das "
                f"raízes aprovadas {reais}. O caminho vem de `.git`/`commondir`, "
                "que o repositório escreve — aceitá-lo deixaria o repositório "
                "escolher onde o NOMOS grava")

    # Confusão CROSS-REPO, e ela sobra mesmo com o git dir DENTRO das raízes.
    # MEDIDO: um repo `hostil` cujo `.git` é o arquivo `gitdir: <vitima>/.git`
    # faz `git-add` sobre `hostil` estagiar no índice de `vitima` — os dois
    # dentro das raízes, então o teste acima passa. O operador aprovou operar em
    # `hostil`; o efeito caiu em `vitima`, e a auditoria registra alvo=hostil.
    #
    # O discriminador é medido e estável: só o `.git`-ARQUIVO chega aqui com git
    # dir alheio, e no ataque esse git dir é a MAIN git dir de OUTRA working tree
    # — basename `.git`, e o pai é uma working tree que não é o `repo` pedido.
    # Worktree ligada (`.git/worktrees/<n>`), submódulo (`.git/modules/<n>`) e
    # `--separate-git-dir <x>` nunca têm o git dir chamado `.git`, então passam.
    base = Path(supervisor.existente(repo))
    ponto = base / ".git"
    if not ponto.is_dir():
        _conferir_titularidade(base, git_dir)
    return git_dir, common


def _conferir_titularidade(base: Path, git_dir: str) -> None:
    """O git dir alheio tem de PROVAR que pertence a esta working tree.

    Quando `.git` é DIRETÓRIO não há o que provar: o git dir mora dentro do
    repositório. Quando é ARQUIVO (ou symlink), o repositório APONTA para um git
    dir que pode ser de outra pessoa — e `_dentro()` não ajuda, porque no ataque
    os dois repositórios estão dentro das mesmas raízes aprovadas.

    ## Por que reconhecer o formato do caminho NÃO bastava

    A primeira correção exigia `gd.name != '.git'`, e a bateria adversarial a
    derrubou em duas formas, ambas com o segredo indo parar no repositório da
    vítima e o commit entrando na história dela:

        hostil/.git  ->  gitdir: <vitima>/vitima-gd      (--separate-git-dir)
        hostil/.git  ->  gitdir: <super>/.git/modules/n  (submódulo)

    Os dois têm basename diferente de `.git`, então passavam — e o comentário
    daquela versão declarava os dois layouts seguros. Reconhecer FORMA de
    caminho é frágil por construção: quem escolhe o caminho é o atacante.

    ## O que o Git registra, e que o atacante não consegue forjar de graça

    Titularidade é dado, não formato, e o Git a grava nos dois layouts que
    dependem de indireção:

        worktree ligada   <git_dir>/gitdir  ->  <repo>/.git      (backpointer)
        submódulo         <git_dir>/config  ->  core.worktree = <repo>

    Ambos apontam DE VOLTA para a working tree dona. No ataque eles apontam para
    a vítima, não para o repositório pedido — que é exatamente a pergunta certa.

    ## `--separate-git-dir` é RECUSADO, e isso é decisão consciente

    Esse layout não registra dono nenhum: o git dir de `--separate-git-dir` é
    indistinguível, byte a byte, entre o uso legítimo e o roubo. Aceitar
    significaria aceitar a forma de ataque junto, porque não há evidência que as
    separe. Fail-closed é a escolha; a mensagem diz o que fazer.
    """
    gd = Path(supervisor.canonicalizar(git_dir))
    alvo = str(supervisor.canonicalizar(base))

    def recusar(dono: str, onde: str) -> None:
        raise supervisor.ErroSeguranca(
            f"o `.git` de {alvo!r} aponta para o git dir {str(gd)!r}, que "
            f"registra pertencer a OUTRA working tree ({dono!r}, em {onde}). "
            "Operar aqui estagiaria o efeito no repositório do vizinho "
            "enquanto a auditoria registra este alvo — confusão cross-repo")

    # 1) Worktree ligada: `<git_dir>/gitdir` nomeia o `.git` da dona.
    ponteiro = gd / "gitdir"
    if ponteiro.is_file():
        try:
            bruto = ponteiro.read_text("utf-8", "replace").strip()
        except OSError:
            bruto = ""
        if bruto:
            dono = supervisor.canonicalizar(str(Path(bruto).parent))
            if dono != alvo:
                recusar(dono, "<git_dir>/gitdir")
            return

    # 2) Submódulo: `core.worktree` no config do git dir aponta para a dona.
    try:
        texto = (gd / "config").read_text("utf-8", "replace")
    except OSError:
        texto = ""
    for linha in texto.splitlines():
        chave, sep, valor = linha.partition("=")
        if not sep or chave.strip().lower() != "worktree":
            continue
        v = valor.strip()
        if not v:
            continue
        caminho = v if os.path.isabs(v) else str(gd / v)
        try:
            dono = supervisor.canonicalizar(caminho)
        except OSError:
            continue
        if dono != alvo:
            recusar(dono, "core.worktree")
        return

    # 3) NENHUM registro de dono. Aqui entra a decisão de dono
    #    `UNPROVABLE_GITDIR_OWNERSHIP = REFUSE`, e ela é o ponto todo desta
    #    função: o NOMOS não aceita um layout só porque o Git nativo aceita.
    #
    #    `--separate-git-dir <x>` não grava dono em lugar nenhum — o git dir é
    #    indistinguível, byte a byte, entre uso legítimo e roubo. Aceitar por
    #    "o Git aceita" seria aceitar junto as duas formas P0 medidas: segredo
    #    estagiado no índice da VÍTIMA e commit na história dela.
    #
    #    Fail-closed é o contrato: `PROVABLE_OWNERSHIP_OR_REFUSE`. A mensagem diz
    #    exatamente o que fazer para voltar ao caminho provável.
    raise supervisor.ErroSeguranca(
        f"o `.git` de {alvo!r} aponta para o git dir {str(gd)!r}, que não "
        "registra dono NENHUM — nem backpointer `<git_dir>/gitdir` (worktree "
        "ligada) nem `core.worktree` (submódulo). Sem prova de titularidade o "
        "layout é indistinguível de roubo cross-repo, e o NOMOS não aceita um "
        "layout só porque o Git nativo aceita: PROVABLE_OWNERSHIP_OR_REFUSE. "
        "Use um repositório com `.git` próprio, uma worktree ligada "
        "(`git worktree add`) ou um submódulo — os três provam a que working "
        "tree o git dir pertence")


def conferir_alternates(repo: Path | str, raizes: tuple[str, ...]) -> None:
    """Nenhum store de objetos ALTERNADO pode sair das raízes aprovadas.

    MEDIDO (A2-REPO.5): `.git/objects/info/alternates` lista diretórios de
    objetos que o Git passa a LER além do próprio store. É um arquivo do
    repositório, e com ele `git-add`/`git-commit` alcançam objetos de um store
    ESTRANGEIRO — `git cat-file -t <sha de fora>` passou de rc=128 para rc=0. As
    consequências são duas: um commit pode ficar dependente de um store que o
    NOMOS nunca aprovou (history quebrada sem ele), e um `push` posterior
    publicaria objetos de outro repositório.

    A regra é a mesma do git dir: alternate é mecanismo legítimo (clone
    `--reference`, store compartilhado), então não se proíbe — exige-se que o
    destino esteja dentro das mesmas raízes que já foram aprovadas. Quem aprovou
    a raiz aprovou o que mora nela, e nada além.

    Lê tanto o git dir quanto o common dir: em worktree ligada os objetos vivem
    no common, e é lá que o `alternates` efetivo mora.
    """
    if not raizes:
        return
    git_dir, common = diretorio_git(repo)
    reais = tuple(supervisor.canonicalizar(r) for r in raizes)
    vistos: set[str] = set()
    for base in (git_dir, common):
        arquivo = Path(base) / "objects" / "info" / "alternates"
        try:
            bruto = arquivo.read_text("utf-8", "replace")
        except OSError:
            continue
        for linha in bruto.splitlines():
            entrada = linha.strip()
            # Formato do Git: comentário com `#`, linha vazia ignorada. Caminho
            # relativo é resolvido contra `<base>/objects`.
            if not entrada or entrada.startswith("#"):
                continue
            if entrada in vistos:
                continue
            vistos.add(entrada)
            alvo = (entrada if os.path.isabs(entrada)
                    else str(Path(base) / "objects" / entrada))
            try:
                resolvido = supervisor.canonicalizar(alvo)
            except OSError:
                resolvido = alvo
            if not _dentro(resolvido, reais):
                raise supervisor.ErroSeguranca(
                    f"o repositório declara um store de objetos alternado em "
                    f"{resolvido!r}, FORA das raízes aprovadas {reais}. O "
                    "arquivo `objects/info/alternates` é do repositório, e por "
                    "ele o Git lê — e um commit passa a depender de — um store "
                    "que ninguém aprovou. Alternate legítimo mora dentro das "
                    "raízes")


def _dentro(caminho: str, raizes: tuple[str, ...]) -> bool:
    """Contenção por COMPONENTE, nunca por prefixo de string.

    `str.startswith` aceitaria `/raiz-do-atacante` como se estivesse dentro de
    `/raiz`. `os.path.commonpath` compara componente a componente, que é a
    pergunta que se quer fazer.
    """
    real = supervisor.canonicalizar(caminho)
    for raiz in raizes:
        try:
            if os.path.commonpath([real, raiz]) == raiz:
                return True
        except ValueError:
            continue          # drives/volumes diferentes: não está dentro
    return False


def confinamento_de_leitura(repo: Path | str,
                            autoridade: "AutoridadeDeRepo | None" = None,
                            ) -> supervisor.Confinamento:
    """Capacidades object-only: NENHUMA escrita no repositório.

    Medido: `git-log`, `git-show` e `git-diff(refA, refB)` produzem saída
    byte-idêntica à execução sem sandbox sem um único allow de escrita. O
    `/dev/null` que o perfil sempre emite continua necessário porque
    `GIT_CONFIG_GLOBAL=/dev/null` é aberto em leitura E escrita.

    É a maior redução barata desta fase: uma capacidade de leitura que
    fisicamente não consegue escrever, em vez de uma que promete não escrever.
    """
    # `autoridade` fecha o TOCTOU: quando o chamador já validou a identidade,
    # o confinamento usa AQUELA, em vez de reler `.git` do disco — que é
    # exatamente onde o escritor concorrente entra.
    if autoridade is not None:
        git_dir, comum = autoridade.git_dir, autoridade.common
    else:
        git_dir, comum = diretorio_git(repo)
    raizes = (supervisor.existente(repo), git_dir)
    if comum != git_dir:
        raizes += (comum,)
    return supervisor.Confinamento(escrita=(), declara_sem_escrita=True,
                                   leitura=raizes,
                                   exec_permitido=executaveis_de_git())


def confinamento_de_repo(repo: Path | str, rede: bool = False,
                         autoridade: "AutoridadeDeRepo | None" = None,
                         ) -> supervisor.Confinamento:
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
    # Ver `AutoridadeDeRepo`: com a autoridade ligada, esta função deixa de ser
    # mais um ponto de releitura de `.git`.
    if autoridade is not None:
        raizes = autoridade.raizes_de_escrita
    else:
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
    # C3 — A LEITURA AINDA NÃO É DECLARADA, e isso é um ACHADO ABERTO, não um
    # esquecimento. Sem `leitura`, `_bloco_de_leitura` emite `(allow file-read*)`
    # GLOBAL: o processo do Git lê o disco inteiro durante `add`/`commit`.
    #
    # Severidade medida: P1, defesa em profundidade. Os dois canais que
    # transformavam "pode ler" em "conteúdo sai" já estão fechados —
    # `core.worktree` (P0.3) e symlink no filtro governado (A2-REPO/C3) — então
    # não é bypass vivo.
    #
    # A redução FOI implementada e medida nesta rodada, e revertida por medição:
    # com `leitura=(existente(repo),) + raizes` a suíte cai em 10 testes que NÃO
    # são deste contrato, e cada grupo pede uma decisão própria:
    #
    #   c2c_integracao / c2c_residual (7)  as SONDAS de controle positivo
    #       precisam ler o interpretador e o binário da sonda, fora do repo.
    #       Conserto é de ARNÊS: declarar a raiz de leitura da sonda no
    #       confinamento que o TESTE monta. Não muda produto.
    #
    #   c2a_tag (3)                        o repo hostil declara
    #       `include.path` para FORA do repositório. O Git trata include
    #       ilegível como FATAL, então a operação passa a falhar fechada em vez
    #       de ler o arquivo. É mais seguro e é MUDANÇA DE CONTRATO: o
    #       repositório ganha um jeito de NEGAR a própria operação. Trocar
    #       leitura-ampla por DoS-pelo-repo é decisão de dono, não de quem
    #       corrige.
    #
    # LANDMINE, para quem retomar: é `existente()`, NUNCA `canonicalizar()`.
    # Com `canonicalizar` são 32 falhas com `fatal: Unable to read current
    # working directory` — os ancestrais saem `/private/var/...` e o processo
    # enxerga `/var/...`.
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
        # A2-REPO: o `.git` do repositorio pode ser um ARQUIVO apontando o git
        # dir para fora das raizes aprovadas, e o git dir vira RAIZ DE ESCRITA
        # do sandbox. Conferir aqui, junto do `resolver`, porque e aqui que as
        # raizes existem — e antes de qualquer I/O que use o caminho.
        conferir_git_dir(repo, ctx.raizes)
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
