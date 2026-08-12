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

import errno
import os
import re
import stat
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


def helpers_de_transporte() -> tuple[str, ...]:
    """Os binários que o Git usa para falar HTTP(S), e que NÃO são o `git`.

    MEDIDO, e desmente a suposição que a allowlist de `push` nasceu com: o
    docstring dizia que os helpers compartilham o inode do `git` e que "dois
    literais já cobrem os helpers". É verdade para `git-receive-pack` e
    `git-upload-pack` (hardlink do mesmo inode), e FALSO para o transporte
    remoto — neste host:

        /usr/bin/git                          inode 1152921500312567503
        <exec-path>/git-remote-http           inode 413740063

    Com só os dois literais de git, TODO push http/https morria em
    `fatal: cannot exec 'git-remote-http': Operation not permitted`, sem chegar
    a abrir conexão. Fail-closed, mas quebrando o caso legítimo — e um contrato
    que só funciona para `file://` não é o contrato que `git-push` promete.

    Derivado em runtime pelo mesmo motivo de `executaveis_de_git`: fixar o
    caminho do Xcode quebraria depois de `xcode-select -s`. Ausência não é erro
    — um host sem os helpers simplesmente não faz push http, e a allowlist sai
    menor em vez de mais permissiva.
    """
    dev = os.path.realpath("/var/select/developer_dir")
    base = os.path.join(dev, "usr", "libexec", "git-core")
    achados: list[str] = []
    for nome in ("git-remote-http", "git-remote-https", "git-remote-ftp",
                 "git-remote-ftps"):
        caminho = os.path.join(base, nome)
        if os.path.exists(caminho):
            # `realpath`: `git-remote-https` é symlink para `git-remote-http`, e
            # o sandbox casa o caminho REAL.
            real = os.path.realpath(caminho)
            if real not in achados:
                achados.append(real)
    return tuple(achados)


def ler_controle_do_repo(caminho: Path, rotulo: str,
                         maximo: int = 64 * 1024) -> str | None:
    """Lê um arquivo de CONTROLE que o repositório escreve, sem se expor.

    `commondir`, `objects/info/alternates`, `<git_dir>/gitdir` e `config` são
    todos escolhidos pelo REPOSITÓRIO, e esta leitura roda no processo do
    SUPERVISOR — fora do sandbox, com a autoridade do NOMOS. Um `read_text()`
    cru neles custou três achados da mesma família:

        FIFO             `open` sem escritor PENDURA o supervisor, e o prazo do
                         nó só existe depois (`.9.04`)
        symlink p/ fora  o conteúdo de um arquivo fora das raízes é LIDO, e
                         sai inteiro embutido na mensagem de erro (`.9.08`,
                         `.9.10`) — divulgação sem escrita nenhuma

    O guard é o mesmo de `_ler_alvo_do_filtro` e `_instantaneo_do_indice`:
    `O_NOFOLLOW` (o link não é seguido), `O_NONBLOCK` (FIFO retorna na hora em
    vez de pendurar) e `S_ISREG` pelo descritor já aberto. `None` = não há
    arquivo de controle a considerar; a ausência é o caso normal.
    """
    try:
        fd = os.open(caminho, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as e:
        if e.errno in (errno.ELOOP, errno.EMLINK):
            raise supervisor.ErroSeguranca(
                f"{rotulo} é um symlink, e arquivo de controle do repositório "
                "não pode ser link: quem escolhe o destino escolhe o que o "
                "supervisor LÊ, fora do sandbox — o conteúdo de um arquivo de "
                "fora das raízes entraria no processo do NOMOS") from None
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise supervisor.ErroSeguranca(
                f"{rotulo} não é arquivo regular (modo {st.st_mode:o}) — FIFO "
                "e device penduram a leitura do supervisor, que acontece antes "
                "de existir qualquer prazo")
        if st.st_size > maximo:
            raise ErroLimite(
                f"{rotulo} tem {st.st_size} bytes (limite {maximo}) — recuso "
                "em vez de ler entrada ilimitada vinda do repositório")
        return os.read(fd, st.st_size).decode("utf-8", "replace")
    finally:
        os.close(fd)


def _ler_ponto_git(base: Path, raizes: tuple[str, ...] = ()) -> tuple[str, str]:
    """A FORMA de `.git` e seu conteúdo, de UM único descritor.

    MEDIDO (`.7.14`), e é a razão de esta função existir: `conferir_git_dir` lia
    `.git` DUAS vezes — uma em `diretorio_git` (para resolver o git dir) e outra
    num `os.lstat` (para decidir se o gate de titularidade dispara). Trocando
    `.git` de ARQUIVO para DIRETÓRIO entre as duas, o git dir resolvido era o da
    VÍTIMA (passa `_dentro`, pois está dentro das raízes) e o gate via
    `dentro_do_repo=True`, PULANDO a titularidade por completo. A raiz de escrita
    do sandbox virava `<vitima>/.git` e o segredo era promovido ao store
    permanente dela.

    `AutoridadeDeRepo` fechou o TOCTOU ENTRE chamadores; este fecha o que sobrou
    DENTRO de uma única chamada. A forma do conserto é a mesma: uma leitura
    alimenta todas as decisões.

    `O_NOFOLLOW` recusa `.git` como symlink no próprio open — a forma-link é
    tratada como indireção não-titular pelo chamador, que não a resolve às
    cegas. O `fstat` vem do descritor JÁ aberto, então forma e conteúdo
    descrevem o MESMO objeto, não dois instantes diferentes.
    """
    ponto = base / ".git"
    try:
        # `O_NONBLOCK` porque esta é a PRIMEIRA leitura de todas, e ela roda
        # no supervisor ANTES de o prazo do nó existir. MEDIDO (`.9.04`): `.git`
        # como FIFO sem escritor BLOQUEAVA PARA SEMPRE — nenhum timeout
        # alcançava, porque o prazo só é calculado depois. O guard correto já
        # existia no irmão `ler_controle_do_repo`; este ramo ficara de fora.
        fd = os.open(ponto, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as e:
        if e.errno in (errno.ELOOP, errno.EMLINK):
            # `.git` é SYMLINK. O destino segue sendo resolvido — o link é
            # layout que o Git aceita, e recusá-lo aqui trocaria a recusa
            # informativa ("git dir FORA das raízes") por um "não é repositório
            # git" que esconde a causa. O que NÃO pode é a forma-link contar
            # como `dir`: era exatamente assim que o gate de titularidade era
            # pulado. Devolver "link" garante que o chamador exija titularidade,
            # e a conferência de raízes continua valendo sobre o destino.
            alvo = ponto.resolve()
            # AS RAÍZES ANTES DE QUALQUER `stat` (`.9.12`, P2). MEDIDO: este
            # ramo é o ÚNICO lugar em que um symlink é deliberadamente seguido,
            # e o destino era interrogado ANTES de qualquer conferência de
            # escopo. Não era só a leitura — era um ORÁCULO DE SISTEMA DE
            # ARQUIVOS sobre caminho ARBITRÁRIO do host, todo ele legível pela
            # EXCEÇÃO que voltava:
            #
            #   /etc/passwd            -> "arquivo .git ilegível"      (existe)
            #   /etc/nao-existe        -> "não é repositório git"      (ausente)
            #   /var/db/sudo           -> "git dir FORA das raízes"    (diretório)
            #   arquivo de 123457 B    -> "tem 123457 bytes"           (TAMANHO)
            #   FIFO / /dev/null       -> "modo 10644" / "modo 20666"  (st_mode)
            #
            # e, quando o alvo começava com `gitdir:`, o RESTO do conteúdo saía
            # embutido na mensagem. Uma chave privada de fora das raízes entrou
            # no processo do supervisor com `texto` completo.
            #
            # `_dentro` primeiro elimina os cinco de uma vez: o repositório só
            # interroga o que ele já podia ler. O caminho aparece na mensagem
            # porque é ENTRADA DELE, não conteúdo do host.
            reais = tuple(supervisor.canonicalizar(r) for r in raizes)
            if not reais or not _dentro(str(alvo), reais):
                raise supervisor.ErroSeguranca(
                    f"o `.git` de {str(base)!r} é symlink para {str(alvo)!r}, "
                    f"FORA das raízes aprovadas {reais}. Seguir o link para ler "
                    "o destino é o repositório escolhendo QUAL arquivo do host o "
                    "supervisor abre — e a própria falha ao abrir já responde "
                    "existência, tipo, modo e tamanho de qualquer caminho"
                ) from None
            # MEDIDO (`.9.11`): este ramo fazia `read_text()` SEM limite, sem
            # `O_NONBLOCK` e sem `S_ISREG` — `.git` como symlink para um arquivo
            # FORA das raízes era lido POR INTEIRO para dentro do processo do
            # supervisor. Os dois ramos da mesma função tinham garantias
            # OPOSTAS: o de arquivo regular limitava a 64 KiB, o de link não
            # limitava nada. `ler_controle_do_repo` é o guard que já existe.
            if alvo.is_dir():
                return "link", ""
            conteudo = ler_controle_do_repo(alvo, ".git (destino do symlink)")
            if conteudo is None:
                return "ausente", ""
            return "link-arquivo", conteudo.strip()
        return "ausente", ""
    try:
        st = os.fstat(fd)
        if stat.S_ISDIR(st.st_mode):
            return "dir", ""
        if not stat.S_ISREG(st.st_mode):
            return "ausente", ""
        if st.st_size > 64 * 1024:
            raise ErroInvalido(
                f"arquivo .git de {base} tem {st.st_size} bytes — recuso em vez "
                "de ler entrada ilimitada vinda do repositório")
        return "arquivo", os.read(fd, st.st_size).decode("utf-8", "replace").strip()
    finally:
        os.close(fd)


def _resolver_git_dir(repo: Path | str,
                      raizes: tuple[str, ...] = ()) -> tuple[str, str, str]:
    """`(git_dir, common, forma_do_ponto_git)` — a forma vem da MESMA leitura.

    Existe para que `conferir_git_dir` decida o gate de titularidade com o
    resultado que JÁ resolveu o git dir, em vez de um segundo `stat` que o
    repositório pode ter trocado no meio (`.7.14`).
    """
    return _diretorio_git_com_forma(repo, raizes)


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
    return _diretorio_git_com_forma(repo)[:2]


def _diretorio_git_com_forma(repo: Path | str,
                             raizes: tuple[str, ...] = ()) -> tuple[str, str, str]:
    base = Path(supervisor.existente(repo))
    forma, texto = _ler_ponto_git(base, raizes)
    if forma in ("dir", "link"):
        # `link` = `.git` é symlink para um DIRETÓRIO git. Resolve normalmente;
        # o que muda é que o chamador NÃO o trata como `dir` para efeito de
        # titularidade (ver `conferir_git_dir`).
        git_dir = supervisor.existente(base / ".git")
    elif forma in ("arquivo", "link-arquivo"):
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
    bruto_comum = ler_controle_do_repo(comum, "<git_dir>/commondir")
    if bruto_comum is not None:
        bruto = bruto_comum.strip()
        common = supervisor.existente(
            bruto if os.path.isabs(bruto) else str(Path(git_dir) / bruto))
    else:
        common = git_dir
    return git_dir, common, forma


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

    # A IDENTIDADE, e não só o caminho. MEDIDO (`.7.14`, `N-A7-01`, `N-A7-02`,
    # os três P0 da 4ª medição): ligar a autoridade como STRING fecha o TOCTOU
    # entre CHAMADORES e deixa aberto o que vem DEPOIS dela — todo consumidor
    # RE-RESOLVE o caminho na hora de agir:
    #
    #   supervisor.perfil()      canonicaliza `conf.escrita` ao emitir o SBPL
    #   _gravar_atomico          mkstemp(dir=alvo.parent), por caminho
    #   _restaurar_refs          mkdir(parents=True) + gravação, por caminho
    #   _promover_quarentena     canonicaliza os DOIS lados pelo MESMO symlink
    #
    # Trocar `<repo>/.git` (diretório próprio, DENTRO das raízes) por SYMLINK
    # para um git dir de FORA, depois da validação, bastava: 12/12 perfis do
    # sandbox emitiram `(allow file-write* (subpath "<fora>/gd"))`; `git-tag`
    # governado saiu `ok=True` criando ref no repositório de fora; `git-log`
    # devolveu a história dele; e o SUPERVISOR (fora do sandbox) sobrescreveu
    # índice e reflog de terceiro pelo DESFAZER, 20/20 — com o NOMOS relatando
    # a operação como RECUSADA.
    #
    # `(st_dev, st_ino)` é a identidade que o caminho não carrega. Um symlink
    # plantado no lugar do diretório resolve para outro inode, e a divergência
    # é observável sem confiar em nenhuma releitura de conteúdo.
    ident_git: tuple[int, int] = (-1, -1)
    ident_common: tuple[int, int] = (-1, -1)

    @property
    def raizes_de_escrita(self) -> tuple[str, ...]:
        return ((self.git_dir,) if self.common == self.git_dir
                else (self.git_dir, self.common))

    def conferir_identidade(self, onde: str) -> None:
        """O caminho ligado ainda aponta para o MESMO objeto? Ou recusa.

        Chamada IMEDIATAMENTE antes de cada efeito que precisa cair no
        repositório validado — emitir o perfil do sandbox, desfazer, promover.
        Depois dela ainda resta janela (o `perfil()` re-resolve microssegundos
        depois), e é por isso que a checagem fica o mais perto possível do uso:
        o que ela elimina é a janela de MILISSEGUNDOS que a medição explorou,
        não a de instruções.
        """
        if self.ident_git == (-1, -1):
            return                       # autoridade construída sem identidade
        for caminho, esperado, rotulo in (
                (self.git_dir, self.ident_git, "git dir"),
                (self.common, self.ident_common, "common dir")):
            try:
                st = os.stat(caminho)
            except OSError as e:
                raise supervisor.ErroSeguranca(
                    f"o {rotulo} {caminho!r} ligado a esta operação sumiu antes "
                    f"de {onde} ({type(e).__name__}). O repositório trocou o "
                    "objeto depois da validação — recuso em vez de agir sobre "
                    "o que estiver lá agora") from None
            if (st.st_dev, st.st_ino) != esperado:
                raise supervisor.ErroSeguranca(
                    f"o {rotulo} {caminho!r} NÃO é mais o objeto validado "
                    f"(inode {esperado} -> {(st.st_dev, st.st_ino)}) na hora de "
                    f"{onde}. Trocar `.git` por symlink depois da validação move "
                    "o efeito para um repositório que ninguém aprovou — medido "
                    "com o sandbox recebendo raiz de escrita FORA das raízes e "
                    "com o supervisor sobrescrevendo índice e reflog de terceiro")


def autoridade_de(repo: Path | str, git_dir: str, common: str) -> AutoridadeDeRepo:
    def ident(p: str) -> tuple[int, int]:
        try:
            st = os.stat(p)
            return (st.st_dev, st.st_ino)
        except OSError:
            return (-1, -1)
    return AutoridadeDeRepo(repo=str(supervisor.existente(repo)),
                            git_dir=git_dir, common=common,
                            ident_git=ident(git_dir),
                            ident_common=ident(common))


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
    git_dir, common, forma = _diretorio_git_com_forma(repo, raizes)
    if not raizes:
        # Sem raízes, esta função não tem contra o que conferir — e a versão
        # anterior RETORNAVA sem conferir, "corrija o chamador". MEDIDO (`.7.03`):
        # um `CapabilityContext` com `raizes=()` construído à mão desligava a
        # defesa por completo, e o escape do `.git`-arquivo voltava a gravar
        # índice e objeto FORA das raízes.
        #
        # Os caminhos sancionados já barram a montante (`registrar_git_tree`
        # levanta sem raízes), então nenhum fluxo legítimo chega aqui vazio.
        # Fail-closed é a resposta correta para o que resta: um escopo vazio é
        # ausência de autoridade, não autoridade ilimitada. Recusar em vez de
        # confiar num palpite fecha o furo de contrato do composition root.
        raise supervisor.ErroSeguranca(
            "conferir_git_dir chamado com raízes VAZIAS — escopo vazio é "
            "ausência de autoridade, não autoridade ilimitada. Nenhum caminho "
            "governado monta contexto sem raízes; recuso em vez de deixar o "
            "efeito cair onde o `.git` do repositório apontar")
    reais = tuple(supervisor.canonicalizar(r) for r in raizes)
    for rotulo, caminho in (("git dir", git_dir), ("common dir", common)):
        if not _dentro(caminho, reais):
            raise supervisor.ErroSeguranca(
                f"{rotulo} do repositório resolve para {caminho!r}, FORA das "
                f"raízes aprovadas {reais}. O caminho vem de `.git`/`commondir`, "
                "que o repositório escreve — aceitá-lo deixaria o repositório "
                "escolher onde o NOMOS grava")

    # O GIT DIR NUNCA É A PRÓPRIA WORKING TREE (`.1.N1`, P1).
    #
    # MEDIDO: `<repo>/.git` = arquivo `gitdir: .` (ou `./`, ou o caminho
    # absoluto do próprio repo) faz o git dir resolver para a WORKING TREE. O
    # layout é AUTO-CERTIFICANTE: a prova de titularidade exigida
    # (`[core] worktree`) é lida de `<gd>/config` = `<repo>/config`, um arquivo
    # da working tree — escrito pelo próprio atacante. `_conferir_titularidade`
    # aceita porque dono == alvo, e a prova é produzida por quem ela deveria
    # autenticar.
    #
    # A consequência não é fuga de raiz (o alvo continua dentro delas): é
    # EXPANSÃO DE AUTORIDADE DENTRO das raízes, escolhida pelo repositório.
    # Contraste medido no mesmo processo:
    #
    #     repo normal   confinamento_de_repo().escrita = ('<repo>/.git',)
    #     repo hostil   confinamento_de_repo().escrita = ('<repo>',)   <-- TUDO
    #
    # Isso revoga a invariante que `confinamento_de_repo` declara e justifica
    # com medição — "a escrita para no DIRETÓRIO GIT, a working tree fica fora",
    # cujo motivo é que "com o repo inteiro liberado, um `filter.clean` hostil
    # SOBRESCREVEU um arquivo do projeto durante o `git add`". É a negação exata
    # de REPOSITORY_CANNOT_EXPAND_NOMOS_AUTHORITY.
    #
    # Por INODE e não por texto: `gitdir: .`, `gitdir: ./`, `gitdir: <abs>` e
    # `gitdir: sub/..` são o mesmo objeto por caminhos diferentes, e comparar
    # strings deixaria as variantes passando. Nenhum layout que o Git produz tem
    # git dir == working tree: repo comum tem `.git/` DENTRO da working tree
    # (inodes distintos), worktree ligada e submódulo apontam para fora dela, e
    # repo BARE não tem working tree para confundir.
    try:
        st_base = os.stat(supervisor.existente(repo))
        st_gd = os.stat(git_dir)
    except OSError as e:
        raise supervisor.ErroSeguranca(
            f"não consegui confrontar git dir e working tree ({type(e).__name__})"
            " — sem essa comparação um `.git` auto-referente passa despercebido"
        ) from None
    if (st_base.st_dev, st_base.st_ino) == (st_gd.st_dev, st_gd.st_ino):
        raise supervisor.ErroSeguranca(
            f"o git dir de {str(repo)!r} É a própria working tree (mesmo inode) "
            "— layout AUTO-CERTIFICANTE: a prova de titularidade "
            "(`[core] worktree`) sai de um arquivo que a working tree contém, "
            "logo é escrita por quem ela deveria autenticar. Aceitá-lo faz a "
            "raiz de ESCRITA do sandbox deixar de ser o git dir e passar a ser "
            "o repositório INTEIRO, e um `filter.clean` hostil sobrescreve "
            "arquivo do projeto durante o `git add`. Nenhum layout que o Git "
            "produz tem git dir igual à working tree")

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
    # A FORMA de `.git` vem da MESMA leitura que resolveu o git dir logo acima
    # (`_ler_ponto_git`), e não de um segundo `stat`. MEDIDO (`.7.14`): com duas
    # leituras, trocar `.git` de ARQUIVO para DIRETÓRIO entre elas fazia o git
    # dir resolvido ser o da VÍTIMA — dentro das raízes, então `_dentro` passa —
    # enquanto o gate via `dentro_do_repo=True` e PULAVA a titularidade. O
    # sandbox passava a escrever no `.git` da vítima e o segredo era promovido
    # ao store permanente dela.
    #
    # `link` conta como indireção: `.git` como symlink é destino escolhido pelo
    # repositório, e tem de provar titularidade como qualquer outra indireção.
    dentro_do_repo = forma == "dir"
    if not dentro_do_repo:
        _conferir_titularidade(base, git_dir)

    # O COMMON DIR é a SEGUNDA indireção, e ela tem dono próprio. Estar dentro
    # das raízes não basta: com `.git` DIRETÓRIO e `commondir` apontando para o
    # git dir de outro repositório — ambos na raiz aprovada — o efeito inteiro
    # cai no vizinho e `_conferir_titularidade` sequer é chamada, porque o gate
    # acima (corretamente) não dispara.
    #
    # A única relação que o Git produz entre common e git dir é a de worktree
    # ligada: `<common>/worktrees/<nome>`. Exigir essa forma é exigir que os
    # dois pertençam ao MESMO repositório.
    if common != git_dir:
        gd = Path(supervisor.canonicalizar(git_dir))
        cm = Path(supervisor.canonicalizar(common))
        # `.git` DIRETÓRIO fecha a questão ANTES da forma do caminho (`.1.07`).
        # MEDIDO: um repositório COMUM cujo diretório se chama literalmente
        # `worktrees`, criado dentro do `.git` da vítima, satisfaz
        # `gd.parent.name == "worktrees" and gd.parent.parent == cm` — a forma
        # casa sem que exista worktree ligada nenhuma. Com `commondir`
        # declarado, `git-add` devolveu ok=True e
        # `AWS_SECRET_ACCESS_KEY=VAZOU_1_07` foi parar no OBJECT STORE DA
        # VÍTIMA, e o `git-commit` seguinte AVANÇOU A REF dela.
        #
        # O Git honra o `commondir` aqui, e isso não muda a decisão: a questão
        # não é o que o Git faz, é o repositório redirecionar a autoridade de
        # ESCRITA concedida para o git dir do vizinho. E há um invariante que
        # não depende de reconhecer nome de diretório: `git worktree add` e
        # submódulo SEMPRE deixam `.git` como ARQUIVO na working tree ligada.
        # Logo `.git` como DIRETÓRIO nunca é worktree ligada nem submódulo, e
        # `commondir` não tem para onde redirecionar.
        if forma == "dir" or gd.parent.name != "worktrees" or gd.parent.parent != cm:
            raise supervisor.ErroSeguranca(
                f"o `commondir` de {str(base)!r} aponta para {str(cm)!r}, que "
                f"não é o repositório do git dir {str(gd)!r}. A única relação "
                "legítima entre os dois é a de worktree ligada "
                "(`<common>/worktrees/<nome>`); qualquer outra faz o efeito "
                "cair no repositório do vizinho enquanto a auditoria registra "
                "este alvo")
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
    #
    # SÓ VALE onde o Git REALMENTE lê esse arquivo: um git dir de worktree
    # ligada, que mora em `<common>/worktrees/<nome>`. MEDIDO: num git dir
    # PRINCIPAL o Git IGNORA `gitdir` por completo — então plantar 85 bytes lá
    # dentro forjava a prova sem mudar nada no comportamento do Git, e a vítima
    # seguia normal em toda inspeção. Confrontar com o que o Git honra é a
    # diferença entre ler um dado e aceitar uma afirmação do atacante.
    ponteiro = gd / "gitdir"
    if gd.parent.name == "worktrees" and ponteiro.is_file():
        bruto = (ler_controle_do_repo(ponteiro, "<git_dir>/gitdir") or "").strip()
        if bruto:
            dono = supervisor.canonicalizar(str(Path(bruto).parent))
            if dono != alvo:
                recusar(dono, "<git_dir>/gitdir")
            return

    # 2) Submódulo: `core.worktree` no config do git dir aponta para a dona.
    #
    # O parse é SENSÍVEL A SEÇÃO, e a versão anterior não era. MEDIDO: uma
    # linha `worktree = <hostil>` sob QUALQUER seção — inclusive uma inventada,
    # `[naoexiste]` — era aceita como prova, e o Git só honra `[core] worktree`.
    # Ou seja: a chave era INERTE para o Git e autoritativa para o NOMOS, que é
    # a pior combinação possível — a adulteração não aparece em nenhuma
    # inspeção de git e mesmo assim decide a titularidade.
    texto = ler_controle_do_repo(gd / "config", "<git_dir>/config") or ""
    secao = ""
    ultimo: str | None = None
    for linha in texto.splitlines():
        crua = linha.strip()
        if crua.startswith("["):
            # A seção tem de ser EXATAMENTE `core`, sem subseção. MEDIDO
            # (`.4.08`): o Git NÃO honra `[core "sub"] worktree`, e o parser
            # anterior pegava o primeiro token e lia como `core` — aceitando
            # como PROVA DE TITULARIDADE uma chave que o Git ignora. Prova
            # forjada é pior que prova ausente: ela passa.
            #
            # E o nome é CASE-INSENSITIVE de verdade: medido, `[CORE]` e
            # `[Core]` são honrados pelo Git. O `.lower()` fica; o que sai é
            # aceitar subseção.
            interno = crua[1:].split("]")[0].strip()
            secao = interno.lower() if " " not in interno and '"' not in interno else ""
            continue
        chave, sep, valor = linha.partition("=")
        if not sep or secao != "core" or chave.strip().lower() != "worktree":
            continue
        v = valor.strip()
        if v:
            # ÚLTIMA declaração vence, como no Git. MEDIDO (`.4.08`): com DOIS
            # `core.worktree` no mesmo `[core]`, o Git honra o ÚLTIMO e este
            # parser aceitava baseado no PRIMEIRO — a prova de titularidade
            # olhava uma chave que o Git ignora. É a mesma classe de divergência
            # que `filter=passa filter=redator` já tinha custado no
            # `.gitattributes`: quem decide a semântica é o Git, e um parser que
            # para na primeira ocorrência lê outro arquivo que não o efetivo.
            ultimo = v
    if ultimo is not None:
        caminho = ultimo if os.path.isabs(ultimo) else str(gd / ultimo)
        try:
            dono = supervisor.canonicalizar(caminho)
        except OSError:
            dono = None
        if dono is not None:
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


# Teto de STORES visitados na cadeia de alternates. Constante de MÓDULO, e não
# local, porque a propriedade que importa é o COMPORTAMENTO AO ESTOURAR — e
# medi-la com o valor real exigiria construir mil repositórios, que é custo sem
# informação nova. Assim o teste baixa o teto e mede a recusa.
MAX_STORES = 1000


def conferir_alternates(repo: Path | str, raizes: tuple[str, ...],
                        autoridade: "AutoridadeDeRepo | None" = None) -> None:
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

    ## Por que a checagem é TRANSITIVA

    MEDIDO (`.5.03`, P1): o Git segue a cadeia de alternates recursivamente — um
    store alcançado por `objects/info/alternates` tem o SEU próprio
    `info/alternates`, e o Git honra o próximo salto. Conferir só o primeiro
    deixava um alternate DENTRO das raízes cujo próprio alternates saía delas:
    com 2 saltos, `git-commit` devolveu ok=True e a história passou a depender
    de um blob que só existe fora das raízes (`git fsck` acusa `missing blob`
    quando o store estrangeiro some). A guarda tem de andar a cadeia inteira,
    como o Git anda.
    """
    if not raizes:
        return
    # MEDIDO: sem consumir a autoridade, esta guarda relia `.git` e passava a
    # conferir um repositório DIFERENTE do que a autoridade ligou. Com um flip
    # concorrente entre as duas leituras, 42/400 e 47/400 tentativas devolveram
    # ok=True sobre um repo cujo store alcança um store FORA das raízes — e as
    # 47 caíram TODAS no git dir da worktree, nenhuma no repo limpo, o que
    # descarta acaso. A guarda tem de olhar o MESMO repositório que o efeito.
    if autoridade is not None:
        git_dir, common = autoridade.git_dir, autoridade.common
    else:
        git_dir, common = diretorio_git(repo)
    reais = tuple(supervisor.canonicalizar(r) for r in raizes)

    # BFS sobre a cadeia de stores de objetos. `fila` guarda diretórios
    # `objects`; `vistos` corta ciclo (um alternate pode apontar de volta) e
    # trabalho repetido. Limite defensivo: cadeia patológica não pode virar
    # varredura ilimitada guiada pelo repositório.
    #
    # ## O teto é FAIL-CLOSED, e antes era uma PORTA (`.5.08`, P1)
    #
    # A condição vivia no `while` e `vistos` crescia por ENTRADA lida. MEDIDO:
    # com 120 alternates de 1º nível TODOS dentro das raízes, `vistos` satura
    # ainda dentro do PRIMEIRO arquivo, o laço termina com a fila cheia e a
    # função RETORNA — sem nunca abrir o `info/alternates` de nenhum deles. Com
    # um 2º salto saindo das raízes: guarda=ACEITOU, e `git cat-file -t` provou
    # que o Git alcança o objeto estrangeiro. Com N=3, a MESMA cadeia é
    # RECUSADA. O bypass não era o conteúdo — era a LARGURA, e quem escolhe a
    # largura é quem escreve o arquivo.
    #
    # Estourar o teto passa a ser RECUSA: se resta fila, a contenção da cadeia
    # não foi provada, e não provar é o mesmo que não conter. Um repositório
    # legítimo tem punhado de alternates; quem chega a mil está construindo
    # exatamente esta saída.
    fila = [str(Path(base) / "objects") for base in (git_dir, common)]
    vistos: set[str] = set()
    while fila:
        objects = fila.pop()
        if objects in vistos:
            continue
        if len(vistos) >= MAX_STORES:
            raise supervisor.ErroSeguranca(
                f"a cadeia de `objects/info/alternates` passa de {MAX_STORES} "
                "stores e não terminou. A varredura para aqui por defesa, e "
                "parar não prova contenção: o resto da cadeia pode sair das "
                f"raízes {reais}. Cadeia desse tamanho não é repositório de "
                "trabalho")
        vistos.add(objects)
        arquivo = Path(objects) / "info" / "alternates"
        bruto = ler_controle_do_repo(arquivo, "objects/info/alternates")
        if bruto is None:
            continue
        for linha in bruto.splitlines():
            entrada = linha.strip()
            # Formato do Git: comentário com `#`, linha vazia ignorada. Caminho
            # relativo é resolvido contra o `objects` que declarou o alternate.
            if not entrada or entrada.startswith("#"):
                continue
            alvo = (entrada if os.path.isabs(entrada)
                    else str(Path(objects) / entrada))
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
                    "que ninguém aprovou. A cadeia é seguida transitivamente, "
                    "como o Git faz. Alternate legítimo mora dentro das raízes")
            if resolvido not in vistos:
                fila.append(resolvido)      # o alternate tem SEU próprio salto


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
        # A IDENTIDADE, agora, e nao so o caminho ligado (`N-A7-01`, P0): o
        # `perfil()` do supervisor RE-RESOLVE `conf.leitura` ao emitir o SBPL,
        # entao a autoridade ligada como string nao alcanca o sandbox. MEDIDO:
        # `git-log` governado devolveu, com ok=True, a historia de um repo de
        # FORA das raizes (6/120).
        autoridade.conferir_identidade("montar o confinamento de leitura")
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
        # Idem para a ESCRITA (`.7.14` / `N-A7-01`, P0). 12/12 perfis emitiram
        # `(allow file-write* (subpath "<fora das raizes>"))` depois de o
        # repositorio trocar `.git` por symlink — e `git-tag` governado criou
        # ref no repositorio de fora com ok=True.
        autoridade.conferir_identidade("montar o confinamento de escrita")
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
        repo, autoridade = self._repo(pedido, ctx)
        argv = self._argv(pedido, repo)
        saida, r = self._rodar(argv, repo, ctx, autoridade)
        self._auditar(ctx, f"git.{pedido.capacidade[4:]}",
                      git_dir=autoridade.git_dir, common_dir=autoridade.common,
                      alvo=supervisor.canonicalizar(repo), bytes=len(saida),
                      sandbox=True, rede=False,
                      classificacao=r.classificacao,
                      morto_por_timeout=r.morto_por_timeout)
        return CapabilityResult.sucesso(saida, efeito_aplicado=False)

    # ------------------------------------------------------------- entradas

    def _repo(self, pedido, ctx) -> tuple[Path, "AutoridadeDeRepo"]:
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
        # BIND AUTHORITY também na LEITURA. MEDIDO: com o retorno descartado,
        # `confinamento_de_leitura` relia `.git` e 63/500 tentativas com
        # escritor concorrente devolveram ok=True contendo a história de um
        # repositório INTEIRAMENTE FORA das raízes. Os adapters de escrita
        # foram convertidos e este ficou para trás — divulgação vale tanto
        # quanto mutação.
        gd, comum = conferir_git_dir(repo, ctx.raizes)
        return repo, autoridade_de(repo, gd, comum)

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
               ctx, autoridade=None) -> tuple[str, supervisor.Resultado]:
        prazo = min(TIMEOUT_S, ctx.restante() or TIMEOUT_S)
        p = supervisor.executar(
            argv, cwd=repo, env=ambiente_minimo(), prazo=prazo,
            confinamento=confinamento_de_leitura(repo, autoridade))
        if p.morto_por_timeout:
            raise ErroLimite(f"git excedeu {prazo:.1f}s")
        if len(p.stdout) > LIMITE_SAIDA:
            raise ErroLimite(f"saída do git acima de {LIMITE_SAIDA} bytes")
        supervisor.conferir_sinal(p, "git")
        if p.returncode != 0:
            erro = p.stderr.decode("utf-8", "replace")[:400]
            raise ErroInvalido(f"git falhou (rc={p.returncode}): {erro}")
        supervisor.conferir_saida(p.stderr, "git")
        return p.stdout.decode("utf-8", "replace"), p
