"""NOMOS adapters.git_tree — C2c: as duas operações que executam código do repo.

`git add` é a única capacidade desta série que roda, por desenho, um programa
escolhido pelo REPOSITÓRIO. `.gitattributes` associa um arquivo a um driver, e
`filter.<driver>.clean` converte working tree em objeto. Não há flag que
desligue isso sem mudar o que fica gravado — medido no C2a: `RC=0`, stderr
vazio, nenhum sinal externo, e o programa do repo executou.

`git commit` entra junto porque depende do índice que o `add` preparou: uma
cadeia é tão confiável quanto o elo que executa código de terceiro.

## A escolha de projeto

As outras capacidades se defendem NEGANDO o mecanismo perigoso — ref que
começa com `-`, refspec livre, destino não governado. Aqui isso não existe: o
mecanismo perigoso É a operação. A defesa muda de natureza — em vez de impedir
a execução, contê-la:

    outras capacidades   o código do repo NÃO executa
    git-add/git-commit   o código do repo executa SEM autoridade

O confinamento vem do `supervisor`: sandbox de filesystem limitado ao próprio
repositório, `deny network*`, process group próprio, rlimits, e timeout que
mata a árvore inteira. Um `filter.clean` hostil roda — e não alcança nada.

## Por que caminhos explícitos e nunca `-A`

`git add -A` adiciona o que estiver no working tree, e o operador aprovou uma
lista. Entre a aprovação e a execução um arquivo pode aparecer. A capacidade
recebe caminhos relativos validados, um a um: o que não foi nomeado não entra.

## Por que a identidade não vem do plano

Autoria de commit é atribuição. Se o plano escolhesse `GIT_AUTHOR_NAME`, o
histórico registraria quem o plano quisesse — e histórico é a evidência que o
NOMOS usa para auditar a si mesmo. A identidade vem do runtime.
"""
from __future__ import annotations

import contextlib
import errno
import os
import re
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:                    # só para o tipo — em runtime o import do
    from nomos.adapters import filtro_governado   # registry é do chamador

from nomos.adapters import supervisor
from nomos.adapters.caminho import resolver
from nomos.adapters.contrato import (
    Adapter, CapabilityContext, CapabilityRequest, CapabilityResult,
    ErroInvalido, ErroLimite,
)
from nomos.adapters.estrito import texto_estrito
from nomos.adapters.git import (
    _NEUTRALIZAR,
    ambiente_minimo,
    autoridade_de,
    confinamento_de_leitura,
    confinamento_de_repo,
    conferir_alternates,
    conferir_git_dir,
    diretorio_git,
)
from nomos.adapters.supervisor import ErroSeguranca

CAPACIDADES = ("git-add", "git-commit")

# ─────────────────── A5.7 — o caminho LEGÍTIMO do filtro ────────────────────
#
# A5 fechou o caminho padrão: um `filter.<driver>.clean` declarado no
# `.git/config` do repositório não executa mais, porque a allowlist de exec do
# sandbox tem só o Git. Essa negação é definitiva e NÃO é o que este bloco
# reabre.
#
# O caso legítimo — redator de segredo, normalizador, LFS — volta a existir por
# outra porta, e com outro dono:
#
#     o repositório PEDE um filtro, por id, no `.gitattributes`
#     o NOMOS DECIDE se existe, qual binário roda, com que argumentos,
#         lendo o quê, escrevendo onde, com que ambiente, prazo e rede
#
# Quem aplica o filtro é o NOMOS, não o Git. A diferença não é estilística: se o
# Git aplicasse, seria preciso pôr o binário do filtro na allowlist de exec do
# processo do Git — e a partir daí quem escolhe o que roda volta a ser a config
# do repositório. Aplicando aqui, a máquina de filtros do Git continua
# PERMANENTEMENTE desligada (`--no-filters` explícito no `hash-object`), e o
# conteúdo transformado entra no índice por `update-index --cacheinfo`.
#
#     .gitattributes  →  id (pedido)      ← única coisa que o repo fornece
#     registry        →  política          ← autoridade do NOMOS
#     artefato        →  o que executa     (A5.3)
#     argv_policy     →  com que argumentos (A5.4)
#     confinamento    →  com que autoridade (A5.5)
#     supervisor      →  stdin/stdout, prazo, árvore (S2 + A5.6)
#
# `filter=<id>` no `.gitattributes` é entrada NÃO CONFIÁVEL: passa por
# `conferir_id` antes de qualquer uso, e id fora da gramática nem chega a virar
# consulta ao registry.
# Não há mais regex de `.gitattributes` aqui, e a ausência é o conserto: quem
# responde "este caminho pede filtro?" é o `git check-attr`, em
# `_pedidos_de_filtro`. Oito formas idiomáticas que o Git honra passavam pelo
# parser próprio sem serem vistas — e cada uma indexava o segredo EM CLARO com
# `ok=True`.
MAX_ATRIBUTOS = 500
MAX_CONTEUDO = 64 * 1024 * 1024
# `ATTR_MAX_FILE_SIZE` do Git (attr.c). Acima dele o Git IGNORA a fonte de
# atributo com um `warning:` e rc=0 — MEDIDO no 2.50.1, discriminante 99 MiB
# redige e 101 MiB não. Serve para DUAS coisas: recusar a fonte que o Git
# ignoraria, e limitar a leitura que o supervisor faz dela.
ATTR_MAX_GIT = 100 * 1024 * 1024

TIMEOUT_S = 60.0
MAX_CAMINHOS = 100
MAX_MENSAGEM = 2000

# Caminho relativo dentro do repositório. Sem `..`, sem absoluto, sem glob —
# glob é o `-A` disfarçado: expande para o que existir no momento.
_CAMINHO_OK = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._/-]{0,255}$")
_CAMINHO_PROIBIDO = re.compile(
    r"(^-)|(^/)|(\.\.)|(//)|([\x00-\x1f;&|`$(){}\[\]<>*?!\\'\":])")

# Chaves que executam programa no caminho de índice/commit. `filter.*.clean`
# NÃO está aqui, e a ausência é deliberada: a chave é variável (`filter.<nome>`)
# e desligá-la mudaria o conteúdo gravado. Contra ela vale o sandbox, não a
# neutralização.
_NEUTRALIZAR_TREE = [
    "-c", "core.fsmonitor=false",
    "-c", "commit.gpgSign=false",
    "-c", "gpg.program=true",
    "-c", "core.editor=true",
    "-c", "commit.template=",
    "-c", "core.hooksPath=/dev/null",
    "-c", "advice.addIgnoredFile=false",
    # A fonte de atributo tem de morar DENTRO do repositório. Sem esta linha o
    # repositório aponta `core.attributesFile` para fora das raízes e o
    # desfecho é o pior dos dois mundos: dentro do sandbox nem o `check-attr`
    # nem o `add` conseguem LER o destino, então ninguém vê pedido de filtro e
    # o conteúdo é indexado CRU com rc=0. Neutralizar faz os dois concordarem
    # em NÃO honrar — e honrar era impossível de qualquer forma.
    #
    # MEDIDO, e é o contraste que sustenta o desenho de `_pedidos_de_filtro`:
    # esta chave o `-c` desliga de verdade; `attr.tree` NÃO (o Git segue lendo
    # a árvore mesmo com `-c attr.tree=`), igualzinho a `core.worktree`. Uma
    # defesa feita só de neutralização ficaria furada exatamente ali — por isso
    # a autoridade sobre atributos é o `check-attr`, não esta lista.
    "-c", "core.attributesFile=",
]


def _abrir_sem_atravessar_link(repo: Path, caminho: str) -> int:
    """Descritor do alvo, com `O_NOFOLLOW` em CADA componente.

    MEDIDO, e é o furo que sobrou depois de A2-REPO: `O_NOFOLLOW` protege
    apenas o ÚLTIMO componente. Com

        sub -> /etc            (symlink de DIRETÓRIO)
        .gitattributes:  sub/hosts filter=redator

    o `lstat`/`open` de `repo/sub/hosts` encontra um arquivo regular — porque o
    `sub` do meio já foi atravessado pelo kernel. O NOMOS lia e indexava
    conteúdo de fora do repositório, no processo do supervisor, fora do sandbox.

    O contraste que torna o achado material: o `git add` CRU recusa isto por
    conta própria (`fatal: pathspec ... is beyond a symbolic link`). O caminho
    governado atravessava uma defesa que o Git já tinha — divergência a MENOS
    de segurança, não a mais.

    Descer componente a componente com `dir_fd` é o único jeito que não tem
    corrida: cada `openat` parte de um descritor já validado, então trocar um
    diretório do meio por link depois da checagem não muda o que foi aberto.
    """
    partes = PurePosixPath(caminho).parts
    fd_dir = os.open(repo, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for componente in partes[:-1]:
            try:
                proximo = os.open(componente,
                                  os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                  dir_fd=fd_dir)
            except OSError as e:
                # MEDIDO no macOS: `O_DIRECTORY|O_NOFOLLOW` sobre symlink-para-
                # diretório devolve ENOTDIR, não ELOOP. Tratar só ELOOP
                # classificaria o ataque como erro de caminho do usuário — a
                # contenção valeria igual, mas o registro mentiria sobre o quê
                # aconteceu, e é do registro que a auditoria vive.
                if e.errno in (errno.ELOOP, errno.EMLINK, errno.ENOTDIR):
                    raise ErroSeguranca(
                        f"{caminho}: o componente {componente!r} é um symlink "
                        "de diretório, e o caminho governado não o atravessa — "
                        "o conteúdo lido viria de fora do repositório, no "
                        "processo do supervisor, fora do sandbox do filtro. O "
                        "próprio `git add` recusa este caminho") from None
                raise ErroInvalido(
                    f"não consegui abrir {componente!r} de {caminho}: {e}") from None
            os.close(fd_dir)
            fd_dir = proximo
        try:
            # `O_NONBLOCK` é obrigatório aqui, e a razão é medida: `open` de
            # FIFO sem escritor BLOQUEIA — no processo do supervisor, antes de
            # existir prazo, exatamente o pendura-tudo que A2-REPO mediu. Com
            # ele o open retorna na hora e o `fstat` logo abaixo recusa por não
            # ser arquivo regular. Para arquivo regular a flag é inócua.
            return os.open(partes[-1],
                           os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                           dir_fd=fd_dir)
        except OSError as e:
            if e.errno in (errno.ELOOP, errno.EMLINK):
                raise ErroSeguranca(
                    f"{caminho} é um symlink, e filtro governado não segue "
                    "link: o conteúdo lido seria o do DESTINO, escolhido pelo "
                    "repositório, e a leitura acontece no processo do "
                    "supervisor — fora do sandbox do filtro. Um link para "
                    "segredo do host viraria conteúdo indexado") from None
            raise ErroInvalido(f"não consegui ler {caminho}: {e}") from None
    finally:
        os.close(fd_dir)


def _ler_alvo_do_filtro(repo: Path, caminho: str) -> bytes:
    """Lê o conteúdo que vai para o filtro governado, SEM seguir link.

    MEDIDO, e era defeito próprio de A5.7: a leitura era `Path.read_bytes()`,
    que segue symlink. Um repositório com

        vaza.txt -> /etc/passwd
        .gitattributes:  *.txt filter=redator

    fazia o NOMOS LER `/etc/passwd` e indexar o conteúdo dele — no processo PAI,
    fora do sandbox, portanto sem nenhuma das fronteiras que A5.5 construiu. O
    confinamento do filtro é irrelevante quando quem lê é o supervisor.

    Havia um segundo erro junto, mais silencioso: o modo gravado saía `100644`,
    isto é, o link virava ARQUIVO REGULAR com o conteúdo do alvo. `git add` de
    um symlink grava o LINK (`120000`), não o destino. O caminho governado
    mudava a semântica do Git sem ninguém pedir.

    A recusa é deliberadamente ESTREITA — só arquivo regular, sem componente
    intermediário que seja link. Symlink não é caso de erro do usuário aqui: é o
    vetor. Quem quiser versionar um link usa o caminho normal, onde o Git grava
    o link como link.
    """
    fd = _abrir_sem_atravessar_link(repo, caminho)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise ErroSeguranca(
                f"{caminho} não é arquivo regular (modo {st.st_mode:o}) — FIFO "
                "e device penduram a leitura do supervisor sem prazo nenhum")
        if st.st_size > MAX_CONTEUDO:
            raise ErroLimite(
                f"{caminho} tem {st.st_size} bytes (limite {MAX_CONTEUDO})")
    except BaseException:
        os.close(fd)
        raise
    try:
        dados = b""
        while len(dados) <= MAX_CONTEUDO:
            bloco = os.read(fd, 1024 * 1024)
            if not bloco:
                return dados
            dados += bloco
        raise ErroLimite(
            f"{caminho} passou de {MAX_CONTEUDO} bytes durante a leitura")
    finally:
        os.close(fd)


@dataclass(frozen=True)
class Identidade:
    """Quem assina o commit. Vem do runtime, nunca do plano."""
    nome: str = "NOMOS"
    email: str = "nomos@localhost"


def caminho_relativo(bruto, indice: int) -> str:
    """Um caminho de working tree seguro, ou `ErroInvalido`."""
    texto = texto_estrito(bruto, f"caminhos[{indice}]", obrigatorio=True,
                          maximo=256)
    if _CAMINHO_PROIBIDO.search(texto):
        raise ErroInvalido(
            f"caminho inválido: {texto!r}. Não pode começar com '-' (o Git "
            "leria como OPÇÃO), ser absoluto, conter '..' ou metacaractere")
    if not _CAMINHO_OK.match(texto):
        raise ErroInvalido(f"caminho fora da gramática: {texto!r}")
    return texto


def mensagem_valida(bruta) -> str:
    texto = texto_estrito(bruta, "mensagem", obrigatorio=True,
                          maximo=MAX_MENSAGEM)
    if texto.startswith("-"):
        raise ErroInvalido(
            "mensagem não pode começar com '-': o Git a leria como opção")
    if any(c in texto for c in "\x00\r"):
        raise ErroInvalido("mensagem com caractere de controle")
    return texto


def _instantaneo_do_indice(repo: Path, autoridade=None,
                           ) -> tuple[Path, bytes | None, int | None]:
    """Copia BRUTA do arquivo de índice, antes da operação.

    O índice é UM arquivo, e ele É o estado completo do que está preparado:
    conteúdo estagiado, estagiamento parcial, renomeação, remoção, modo,
    resolução de conflito. Guardar os bytes captura tudo isso de uma vez.

    É por isso que o rollback NÃO é feito com `git reset`: `reset` é uma
    operação semântica que recalcula o índice a partir de HEAD, e por isso
    destrói justamente os casos que precisamos preservar — um caminho que já
    estava estagiado de propósito, ou estagiado PELA METADE (conteúdo no
    índice diferente do conteúdo na working tree). Restaurar os bytes devolve
    o estado exato; `reset` devolveria um estado plausível.
    """
    git_dir = autoridade.git_dir if autoridade is not None else diretorio_git(repo)[0]
    alvo = Path(git_dir) / "index"
    try:
        st = os.lstat(alvo)
    except OSError:
        # Repositório recém-criado ainda não tem índice. "Restaurar" aqui
        # significa fazer o arquivo deixar de existir de novo.
        return alvo, None, None

    # `.git/index` como SYMLINK é escolha do REPOSITÓRIO, e a leitura acontece
    # AQUI — no processo do supervisor, fora do sandbox. MEDIDO: com
    # `.git/index -> /fora/das/raizes/chave.pem`, `read_bytes()` seguia o link e
    # trazia a chave privada do host para dentro do processo do NOMOS. O `add`
    # falhava depois, e o vazamento já tinha acontecido: nenhuma escrita é
    # necessária para violar confidencialidade.
    #
    # Junto vinha um segundo efeito: `_restaurar_indice` faz `os.replace` sobre
    # o caminho, então o link do repositório era SUBSTITUÍDO por arquivo
    # regular — mutação silenciosa de um repositório que a operação recusou.
    #
    # O índice é estado interno do Git; não existe caso legítimo em que ele
    # precise ser um link. Recusar é estreito e correto.
    if stat.S_ISLNK(st.st_mode):
        raise ErroSeguranca(
            f"{alvo} é um symlink, e o índice não pode ser link: a leitura do "
            "instantâneo acontece no processo do supervisor, FORA do sandbox, "
            "então o destino escolhido pelo repositório seria lido com a "
            "autoridade do NOMOS — e o rollback trocaria o link por arquivo "
            "regular num repositório cuja operação foi recusada")
    if not stat.S_ISREG(st.st_mode):
        raise ErroSeguranca(
            f"{alvo} não é arquivo regular (modo {st.st_mode:o}) — FIFO e "
            "device penduram a leitura do supervisor sem prazo nenhum")
    return alvo, alvo.read_bytes(), st.st_mode


def _gravar_atomico(alvo: Path, dados: bytes, modo: int | None = None) -> None:
    """Escreve `dados` em `alvo` atomicamente, por temporário NÃO ADIVINHÁVEL.

    MEDIDO (`.8.03` e `.8.NEW-ROLLBACK-TMPNAME`): os três restauradores da
    transação usavam nome TOTALMENTE previsível — `.<nome>.nomos-*-<pid>` —
    dentro de diretórios que o REPOSITÓRIO controla. Pré-criar esse caminho como
    DIRETÓRIO derruba o desfazer, e o índice fica com o conteúdo RECUSADO
    estagiado. Não é corrida: é conteúdo ESTÁTICO do repositório, sem oráculo
    nenhum — basta saber o formato do nome.

    `mkstemp` no MESMO diretório resolve, e é o que `_promover_quarentena` já
    fazia: o contraste dentro do próprio arquivo é que denunciava a assimetria.
    Mesmo diretório porque `os.replace` só é atômico dentro de um filesystem.
    """
    fd, temporario = tempfile.mkstemp(dir=alvo.parent, prefix=".nomos-tmp-")
    try:
        with os.fdopen(fd, "wb") as saida:
            saida.write(dados)
            saida.flush()
            os.fsync(saida.fileno())
        if modo is not None:
            os.chmod(temporario, modo)
        os.replace(temporario, alvo)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporario)
        raise


def _instantaneo_do_split(autoridade) -> dict[str, bytes]:
    """Bytes dos `sharedindex.<sha>`, que o índice pode REFERENCIAR.

    MEDIDO: com `core.splitIndex=true` e `splitIndex.sharedIndexExpire=now` —
    ambos config do REPOSITÓRIO — o estado real do índice mora em DOIS arquivos.
    O Git apaga o `sharedindex` antigo durante a operação, e o rollback devolvia
    um `.git/index` apontando para um arquivo que não existe mais: `ls-files`,
    `status` e `commit` passavam todos a sair rc=128, num repositório cuja
    operação foi RECUSADA. O trabalho legítimo que já estava estagiado ia junto.

    Guardar os bytes dos dois é a mesma decisão do índice: estado, não semântica.

    ## O mesmo guard de `.8.04`, e a razão de ele não poder faltar aqui

    `sharedindex.<sha>` é nome que o REPOSITÓRIO controla, e a leitura acontece
    NESTE processo — o do supervisor, fora do sandbox. Um `read_bytes()` cru
    seguiria um symlink plantado para um segredo do host, trazendo o conteúdo
    para dentro do NOMOS: exatamente o vazamento que `_instantaneo_do_indice`
    já recusa sobre `.git/index`. Confidencialidade não precisa de escrita, e a
    assimetria entre os três instantâneos (índice e refs faziam `lstat`, o split
    não) era o furo. `lstat` antes de ler, só arquivo regular.
    """
    estado: dict[str, bytes] = {}
    for base in {autoridade.git_dir, autoridade.common}:
        for p in Path(base).glob("sharedindex.*"):
            try:
                st = os.lstat(p)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):
                # symlink, FIFO, device: o `sharedindex` é estado interno do
                # Git, nunca um link. Recusar em vez de seguir para um destino
                # escolhido pelo repositório.
                raise ErroSeguranca(
                    f"{p} não é arquivo regular (modo {st.st_mode:o}) — "
                    "`sharedindex.<sha>` como symlink/FIFO faria a leitura do "
                    "instantâneo, que roda no processo do supervisor fora do "
                    "sandbox, seguir um destino escolhido pelo repositório")
            try:
                estado[str(p)] = p.read_bytes()
            except OSError:
                continue
    return estado


def _restaurar_split(estado: dict[str, bytes]) -> None:
    """Recria os `sharedindex` que a operação apagou. Best-effort por arquivo."""
    for caminho, dados in estado.items():
        alvo = Path(caminho)
        if alvo.exists():
            continue
        try:
            _gravar_atomico(alvo, dados)
        except OSError:
            continue


def _restaurar_indice(inst: tuple[Path, bytes | None, int | None],
                      depois_do_exec: bytes | None = None,
                      antes_do_exec: bytes | None = None) -> bool:
    """Devolve o índice ao estado do instantâneo. Retorna se detectou terceiro.

    O retorno substitui a lista de MÓDULO que existia aqui. MEDIDO (`.8.07`):
    `_TERCEIRO_DETECTADO` era estado global mutável, e duas operações governadas
    no MESMO processo — o `git-commit` que segue um `git-add`, ou dois adapters
    concorrentes — liam e limpavam a lista uma da outra. É a exata violação que
    o adapter documenta evitar ("estado de operação em `self` faria duas
    operações trocarem de plano"). A detecção agora é LOCAL: sobe pelo retorno,
    e cada `executar` decide sobre a sua própria.
    """
    alvo, dados, modo = inst
    if dados is None:
        alvo.unlink(missing_ok=True)
        return False

    # ESCRITOR DE TERCEIRO. MEDIDO 5/5: um `git add` concorrente saía com rc=0,
    # era visto no índice, e o rollback restaurava os bytes antigos APAGANDO o
    # trabalho aceito — sem sinal nenhum para quem o fez. O `index.lock`
    # serializa a escrita, mas não desfaz a corrida: o concorrente venceu ANTES.
    #
    # Aqui a operação já está sendo recusada, então o índice PRECISA voltar (o
    # conteúdo recusado não pode ficar estagiado). O que não pode é a destruição
    # ser SILENCIOSA — por isso o incidente sobe pelo retorno.
    # O DISCRIMINADOR é o estado APÓS o nosso exec, não o instantâneo. MEDIDO
    # (`.11.09`): o `git add`/`commit` do PRÓPRIO NOMOS reescreve o índice
    # (refresh do stat cache), então comparar com o instantâneo acusava
    # "trabalho de terceiro foi perdido" em toda recusa — sem que existisse
    # terceiro nenhum. Um sinal que dispara sempre não é sinal; ele destrói a
    # confiança na única evidência que `.8.03` construiu.
    #
    # Sem `depois_do_exec` (o exec nem chegou a rodar) não há efeito nosso a
    # descontar, e qualquer diferença é de fato de outro processo.
    try:
        atual = alvo.read_bytes()
    except OSError:
        atual = None
    esperado = depois_do_exec if depois_do_exec is not None else dados
    terceiro = atual is not None and atual != esperado
    # ...mas `depois_do_exec` só enxerga a janela EXEC→DESFAZER. MEDIDO
    # (`.8.05-08`, REGRESSION, 12/12): um `git add` de terceiro que entra entre
    # o INSTANTÂNEO e o nosso exec já está DENTRO de `depois_do_exec` — o
    # detector compara duas fotos que ambas o contêm, conclui "igual", e o
    # rollback apaga o trabalho aceito sem emitir nada. O conserto de `.11.09`
    # fechou o falso positivo e abriu este falso NEGATIVO, que é o pior dos
    # dois: silêncio sobre destruição real.
    #
    # A foto tirada IMEDIATAMENTE ANTES do exec fecha a janela cega. Antes do
    # exec não existe efeito nosso a descontar, então qualquer divergência do
    # instantâneo é, por construção, de outro processo.
    if antes_do_exec is not None and antes_do_exec != dados:
        terceiro = True
    # Escrever direto em `index` deixaria uma janela com arquivo truncado, que
    # o Git leria como índice corrompido. `os.replace` no MESMO diretório é
    # rename atômico: ou o índice antigo, ou o restaurado, nunca um meio-termo.
    #
    # NÃO se toma `index.lock` aqui, e isso é MEDIÇÃO, não omissão. A tentativa
    # de serializar o desfazer por esse arquivo COLIDE com o uso que o próprio
    # Git faz dele: sob a bateria de corrida (A9), o `update-index` da operação
    # SEGUINTE passou a morrer com `Unable to create index.lock: File exists`.
    # A defesa criou uma falha nova sem ser o que resolve a propriedade.
    #
    # O que resolve a perda SILENCIOSA de trabalho concorrente é a DETECÇÃO
    # logo acima: se o índice mudou entre o instantâneo e o desfazer, o
    # incidente sobe anexado ao erro. Perda pode ser inevitável numa recusa;
    # perda sem sinal não.
    _gravar_atomico(alvo, dados, modo)
    return terceiro


def _campos_de_autoridade(autoridade) -> dict[str, str]:
    """Os campos que dizem ONDE o efeito realmente caiu.

    MEDIDO: o registro trazia só `alvo` — a working tree que o OPERADOR nomeou.
    Num layout com indireção o efeito cai em outro lugar, e o registro não o
    nomeava em campo nenhum: numa worktree ligada legítima o objeto foi para o
    COMMON DIR, e quem lê a auditoria via `alvo=<raizes>/wt` sem ter como saber.

    Combinado com confusão cross-repo, a auditoria registrava o repositório do
    ATACANTE enquanto o segredo entrava na história da VÍTIMA — o registro
    apontava para o lugar errado exatamente no caso em que ele mais importa.

    A `AutoridadeDeRepo` já carrega os dois resolvidos e VALIDADOS; emiti-los é
    registrar a autoridade que o efeito consumiu, não a que o plano pediu.
    """
    if autoridade is None:
        return {}
    return {"git_dir": autoridade.git_dir, "common_dir": autoridade.common}


def _descer_refs(raiz: Path, estrito: bool) -> list[Path]:
    """Arquivos de ref de UM git dir, descendo COMPONENTE A COMPONENTE.

    ## Por que descida manual e não `rglob` (`.6.08`/`.6.NOVO-08`, P1)

    MEDIDO: `<git_dir>/refs/heads` como SYMLINK DE DIRETÓRIO na PROFUNDIDADE 2,
    com o alvo dentro do git dir, escapa de `d.rglob("*")` — `rglob` NÃO recursa
    em symlink de diretório, e `p.is_file()` descarta o próprio link. As refs
    sob ele (`refs/heads/main`, tags, `refs/replace/*`) somem do instantâneo e
    portanto da TRANSAÇÃO: um `git-commit` governado MUTA uma tag ou INSTALA
    `refs/replace` e devolve ok=True, e uma operação RECUSADA deixa o branch
    AVANÇADO para um objeto que a quarentena destruiu.

    O guard de `.8.NEW-REFSDIR-SYMLINK` via só o componente de PROFUNDIDADE 1
    (`refs`, `logs`). Descer com `os.lstat` em cada nível fecha QUALQUER
    profundidade: um symlink em `refs/`, `logs/` ou abaixo não é forma legítima
    de referência do Git — refs soltas são arquivos regulares e os diretórios
    (`heads`, `tags`, `remotes`) são diretórios reais.

    `estrito`: `_instantaneo_das_refs` RECUSA a operação (o efeito ainda não
    aconteceu); `_refs_agora` (discriminador de autoria) apenas ignora o galho,
    degradando para o lado conservador — nunca destruindo calado.
    """
    alvos = [raiz / "HEAD", raiz / "packed-refs", raiz / "ORIG_HEAD"]
    pilha = [raiz / "refs", raiz / "logs"]
    while pilha:
        d = pilha.pop()
        try:
            modo = os.lstat(d).st_mode
        except FileNotFoundError:
            continue
        except OSError:
            if estrito:
                raise
            continue
        if not stat.S_ISDIR(modo):
            if estrito:
                raise ErroSeguranca(
                    f"{d} não é diretório real (modo {modo:o}) — um symlink em "
                    "refs/ ou logs/, em qualquer profundidade, tira as "
                    "referências sob ele do instantâneo e da transação; um "
                    "commit governado passa a MUTAR tag ou instalar "
                    "refs/replace sem que o desfazer alcance")
            continue
        try:
            entradas = sorted(d.iterdir())
        except OSError:
            if estrito:
                raise
            continue
        for entrada in entradas:
            try:
                m = os.lstat(entrada).st_mode
            except OSError:
                continue
            if stat.S_ISDIR(m):
                pilha.append(entrada)
            elif stat.S_ISREG(m):
                alvos.append(entrada)
            elif estrito:
                raise ErroSeguranca(
                    f"{entrada} não é arquivo nem diretório regular (modo "
                    f"{m:o}) — symlink/FIFO dentro de refs/ ou logs/ não é forma "
                    "legítima de referência, e leria/gravaria fora das raízes no "
                    "processo do supervisor")
    return alvos


def _instantaneo_das_refs(autoridade) -> dict[str, bytes | None]:
    """Bytes de `HEAD`, das refs soltas e do reflog, antes da operação.

    O que se guarda são os ARQUIVOS, pelo mesmo motivo do índice: `git
    update-ref` desfaria semanticamente e não devolveria o reflog, que é parte
    da evidência. Guardar bytes devolve o estado exato.

    A varredura é do git dir E do common (em worktree ligada, `refs/heads` mora
    no common e `HEAD` no git dir da worktree — restaurar só um deixaria o par
    inconsistente, que é justamente a corrupção que isto existe para impedir).
    """
    estado: dict[str, bytes | None] = {}
    bases = {autoridade.git_dir, autoridade.common}
    for base in bases:
        raiz = Path(base)
        # Descida COMPONENTE A COMPONENTE (`_descer_refs`), não `rglob`: o
        # symlink de diretório em profundidade >= 2 é o furo que `rglob` não vê.
        alvos = _descer_refs(raiz, estrito=True)
        for alvo in alvos:
            # `HEAD`, `packed-refs` e `ORIG_HEAD` são nomes que o REPOSITÓRIO
            # controla, e esta leitura roda no processo do supervisor, fora do
            # sandbox — a mesma exposição do `.git/index`. MEDIDO (`.6.09`,
            # `.11.07`): como SYMLINK para fora, `read_bytes` trazia o conteúdo
            # de fora das raízes e o `os.replace` do rollback substituía o link
            # por arquivo regular; como FIFO, a leitura PENDURAVA o supervisor
            # sem prazo. `lstat` + só arquivo regular fecha os dois, sem
            # travar o caminho legítimo (refs e HEAD são sempre arquivos comuns).
            try:
                st = os.lstat(alvo)
            except OSError:
                estado[str(alvo)] = None      # ausente: restaurar = remover
                continue
            if not stat.S_ISREG(st.st_mode):
                raise ErroSeguranca(
                    f"{alvo} não é arquivo regular (modo {st.st_mode:o}) — "
                    "HEAD/refs/reflog como symlink ou FIFO fariam o instantâneo "
                    "ler fora das raízes ou pendurar o supervisor; nenhum deles "
                    "é forma legítima de uma referência do Git")
            try:
                estado[str(alvo)] = alvo.read_bytes()
            except OSError:
                estado[str(alvo)] = None
    return estado


def _refs_agora(autoridade) -> dict[str, bytes | None]:
    """Foto BARATA das refs, para DISCRIMINAR autoria — não para restaurar.

    Não repete a validação de `_instantaneo_das_refs` (essa já rodou, e é ela
    que decide se a operação prossegue): aqui só se quer saber QUAIS arquivos
    de ref existiam num instante. Por isso nada levanta — o que não é arquivo
    regular simplesmente não entra, e a ausência de discriminador degrada para
    o lado conservador (relatar incidente), nunca para o de destruir calado.
    """
    estado: dict[str, bytes | None] = {}
    if autoridade is None:
        return estado
    for base in {autoridade.git_dir, autoridade.common}:
        raiz = Path(base)
        # Mesma descida por componente, modo LENIENTE: o galho com symlink é
        # ignorado (degrada para incidente conservador), não recusado — esta
        # foto é discriminador de autoria, e já rodou o guard estrito antes.
        for alvo in _descer_refs(raiz, estrito=False):
            with contextlib.suppress(OSError):
                if stat.S_ISREG(os.lstat(alvo).st_mode):
                    estado[str(alvo)] = alvo.read_bytes()
    return estado


def _restaurar_refs(estado: dict[str, bytes | None],
                    antes_do_exec: dict[str, bytes | None] | None = None,
                    depois_do_exec: dict[str, bytes | None] | None = None,
                    ) -> bool:
    """Devolve refs, HEAD e reflog ao estado do instantâneo.

    Best-effort por arquivo: uma falha isolada não pode impedir a restauração
    dos outros, senão um erro no meio do desfazer deixaria o repositório PIOR
    que se nada tivesse sido tentado.

    ## O discriminador de AUTORIA, que não existia (`.11.09`, P1)

    O conserto de `.11.09` foi aplicado só ao índice. Aqui o laço abaixo tratava
    como TERCEIRO toda ref fora do instantâneo — inclusive `refs/heads/main` e o
    reflog que o `git commit` do PRÓPRIO NOMOS acabou de criar. Ou seja: um
    incidente forense que dispara SOZINHO, sem concorrência nenhuma, em toda
    recusa de `git-commit`. Sinal que dispara sempre não é sinal — ele torna
    inútil a única evidência que `.8.03` construiu.

    As duas fotos delimitam as três janelas e cada uma tem dono diferente:

        instantâneo ─(A)─ antes_do_exec ─(B: NOSSO exec)─ depois ─(C)─ desfazer

    (A) e (C) são de outro processo — incidente. (B) é nosso — silêncio.
    """
    for caminho, dados in estado.items():
        alvo = Path(caminho)
        try:
            if dados is None:
                alvo.unlink(missing_ok=True)
                continue
            if alvo.exists() and alvo.read_bytes() == dados:
                continue                      # não foi tocado
            alvo.parent.mkdir(parents=True, exist_ok=True)
            _gravar_atomico(alvo, dados)
        except OSError:
            continue
    # Refs CRIADAS pela operação recusada não estão no instantâneo e ficariam
    # órfãs apontando para objeto que a quarentena levou. Mas o laço não
    # distingue "ref criada pela operação recusada" de "ref criada por um
    # TERCEIRO durante a janela" — e destruía as duas. MEDIDO
    # (`.8.NEW-REFS-TERCEIRO`, `.6.N2`): destruição real, e SEM sinal, porque só
    # `_restaurar_indice` tinha canal de incidente. A simetria estava faltando.
    terceiro = False
    # Uma ref MODIFICADA por terceiro na janela (A) já foi sobrescrita pelo laço
    # acima; sem a foto pré-exec isso some calado. Com ela, vira incidente.
    if antes_do_exec is not None:
        for caminho, dados in estado.items():
            if caminho in antes_do_exec and antes_do_exec[caminho] != dados:
                terceiro = True
    for caminho in list(estado):
        raiz = Path(caminho)
        if raiz.name == "HEAD":
            for sub in ("refs", "logs"):
                d = raiz.parent / sub
                if not d.is_dir():
                    continue
                for p in list(d.rglob("*")):
                    if not p.is_file() or str(p) in estado:
                        continue
                    # NOSSO se apareceu entre as duas fotos do exec. Sem as
                    # fotos não há como distinguir, e aí o conservador é acusar
                    # — perder trabalho calado é o defeito maior.
                    nosso = (antes_do_exec is not None
                             and depois_do_exec is not None
                             and str(p) not in antes_do_exec
                             and str(p) in depois_do_exec)
                    if not nosso:
                        terceiro = True
                    with contextlib.suppress(OSError):
                        p.unlink()
    return terceiro


def _abrir_quarentena(repo: Path, autoridade=None,
                      ) -> tuple[supervisor.Quarentena, Path, int]:
    """Object store descartável desta operação, dentro do próprio git dir.

    Fica no git dir porque essa área JÁ é a autoridade de escrita concedida
    (`confinamento_de_repo`), então a quarentena não amplia nada. Um diretório
    em `/tmp` exigiria abrir mais uma raiz de escrita no sandbox — autoridade
    nova para resolver um problema de contenção seria o caminho errado.

    ## O DESCRITOR do git dir sobe junto, e por medição (`.7.19`, P2)

    A limpeza fazia `shutil.rmtree(<git_dir>/nomos-quarentena-*)` — resolvendo o
    CAMINHO de novo, na hora de apagar. O repositório observa o próprio git dir
    e o RENOMEIA assim que a quarentena ganha um arquivo: o caminho deixa de
    existir, `ignore_errors=True` engole a falha, e a limpeza vira no-op
    SILENCIOSO. MEDIDO 8/8 e depois 5/5: operação RECUSADA, índice corretamente
    revertido, `git fsck` limpo — e o blob CRU do arquivo recusado legível em
    `<git dir>/nomos-quarentena-*/`, com
    `zlib.decompress` devolvendo `AWS_SECRET_ACCESS_KEY=...`.

    É o mesmo resolve→valida→descarta→resolve-de-novo que `AutoridadeDeRepo`
    fechou para a autoridade, sobrevivendo no DESFAZER. O descritor segue o
    INODE: renomear o git dir deixa de ter efeito sobre a limpeza.
    """
    if autoridade is not None:
        git_dir, comum = autoridade.git_dir, autoridade.common
    else:
        git_dir, comum = diretorio_git(repo)
    reais = Path(comum) / "objects"
    # `O_NOFOLLOW` no git dir: ele já foi validado pela autoridade, e abrir por
    # caminho seguindo link seria reabrir a mesma indireção que ela consumiu.
    fd = os.open(git_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        raiz = Path(tempfile.mkdtemp(prefix="nomos-quarentena-", dir=git_dir))
    except BaseException:
        os.close(fd)
        raise
    return (supervisor.Quarentena(diretorio=str(raiz), alternativos=str(reais)),
            reais, fd)


def _fechar_quarentena(raiz_q: Path, fd_git_dir: int) -> str:
    """Apaga a quarentena PELO DESCRITOR e PROVA que ela sumiu.

    Devolve "" quando não restou nada, ou a descrição do resíduo. Silêncio aqui
    era o defeito: `ignore_errors=True` transformava "não consegui apagar o
    store com o segredo" em sucesso aparente.
    """
    nome = raiz_q.name
    try:
        try:
            shutil.rmtree(nome, dir_fd=fd_git_dir)
        except FileNotFoundError:
            pass
        except OSError as e:
            return f"{type(e).__name__}: {e}"
        # A PROVA, pelo MESMO descritor: perguntar pelo caminho responderia
        # sobre outro diretório se o git dir tiver sido renomeado no meio.
        # `rmtree` levanta ao falhar, mas "levantou" e "sumiu" são afirmações
        # diferentes, e é a segunda que importa para o segredo em disco.
        try:
            os.stat(nome, dir_fd=fd_git_dir, follow_symlinks=False)
        except FileNotFoundError:
            return ""
        return f"a quarentena {nome} continua no git dir depois da limpeza"
    finally:
        with contextlib.suppress(OSError):
            os.close(fd_git_dir)


# Nomes que a quarentena do Git legitimamente produz. MEDIDO num `add` + `commit`
# reais: só objetos soltos `<2hex>/<38hex>`. `pack/` entra porque o Git pode
# empacotar sob outras condições, e recusar isso quebraria a operação legítima.
_OBJETO_SOLTO = re.compile(r"^[0-9a-f]{2}/[0-9a-f]{38,62}$")
_OBJETO_PACK = re.compile(r"^pack/pack-[0-9a-f]{40,64}\.(pack|idx|rev)$")


def _promover_quarentena(raiz: Path, reais: Path,
                         raiz_do_store: str = "") -> int:
    """Promove os objetos aceitos para o store permanente. TUDO OU NADA.

    A versão anterior movia objeto a objeto com `os.replace`. Cada movimento é
    atômico sozinho, e o CONJUNTO não era — uma falha no meio deixava os
    primeiros já promovidos. MEDIDO, com `ENOSPC` injetado no sexto de doze
    objetos:

        operação RECUSADA (OSError), índice restaurado byte a byte
        e 5 blobs com `AWS_SECRET_ACCESS_KEY=...` LEGÍVEIS no store permanente,
        confirmados como `dangling blob` pelo `git fsck`

    Objeto inalcançável não é objeto ausente: ele continua legível por
    `git cat-file` até um `gc`, e é exatamente o resíduo que A0.3 existe para
    impedir. O rollback do índice funcionava e mascarava o vazamento.

    ## Por que COPIAR e não mover, e por que não `os.link`

    A promoção CRIA o destino sem destruir a origem: assim desfazer é apagar os
    destinos criados, e a quarentena segue intacta para o `rmtree` do chamador.
    Mover exigiria mover de volta no desfazer, e um segundo erro no meio disso
    deixaria o estado pior que o inicial.

    `os.link` faria isso de graça, e foi a primeira implementação — mas viola um
    invariante congelado: `test_c6_nenhuma_capacidade_governada_cria_hardlink`
    varre `adapters/` por `os.link` e falha. O invariante não é decorativo: ele
    é a PREMISSA que torna aceitável a leitura por hardlink dentro da raiz
    (documentada em `test_c6_hardlink_dentro_da_raiz_e_lido`). Enfraquecê-lo
    para economizar uma cópia trocaria uma garantia de fronteira por I/O de
    objeto solto. A cópia fica.

    A publicação de cada objeto é atômica: copia para um temporário no MESMO
    diretório e só então `os.replace` para o nome final. Sem isso, um destino
    parcialmente escrito ficaria visível com nome de objeto válido — e objeto
    truncado é corrupção silenciosa do store.

    Atomicidade real entre N arquivos não existe no POSIX. O que se garante é
    que nenhum objeto fica VISÍVEL no store permanente quando a promoção não
    completa.
    """
    permitida = ""
    if raiz_do_store:
        # O destino não pode ser escolhido pelo repositório. `.git/objects` como
        # SYMLINK apontando para fora fazia a promoção escrever fora do
        # confinamento declarado — o sandbox não vê esta escrita, porque ela
        # acontece no processo do supervisor.
        #
        # A raiz conferida é o COMMON DIR, e não o git dir, porque é dele que
        # `_abrir_quarentena` deriva `reais`. MEDIDO: com o git dir, TODO
        # `git add` numa WORKTREE LIGADA era recusado — lá os objetos moram no
        # common (`main/.git/objects`) e o git dir é `main/.git/worktrees/<n>`,
        # então o guard reprovava o layout legítimo. Nenhum teste pegava porque
        # nenhum exercia `add` em worktree ligada; o repositório desta missão É
        # uma. Guard que confere contra uma raiz diferente da que a operação
        # usa não é guard estrito, é guard errado.
        real = supervisor.canonicalizar(str(reais))
        # `permitida`, e não `raiz`: `raiz` é o PARÂMETRO com o diretório da
        # quarentena, e sombreá-lo trocava um `Path` por `str` — o `rglob` logo
        # abaixo morria com AttributeError no meio da promoção.
        permitida = supervisor.canonicalizar(raiz_do_store)
        if os.path.commonpath([real, permitida]) != permitida:
            raise ErroSeguranca(
                f"o store de objetos resolve para {real!r}, fora da raiz do "
                f"store {permitida!r} — o repositório não escolhe onde o objeto "
                "é promovido")

    pendentes: list[tuple[Path, Path]] = []
    for origem in sorted(raiz.rglob("*")):
        st = os.lstat(origem)
        if stat.S_ISDIR(st.st_mode):
            continue
        if not stat.S_ISREG(st.st_mode):
            # `lstat`, e não `is_file()`: este último SEGUE o link, e um symlink
            # na quarentena promoveria o DESTINO dele para dentro do store.
            raise ErroSeguranca(
                f"quarentena contém {origem.name!r}, que não é arquivo regular "
                f"(modo {st.st_mode:o}) — objeto de Git nunca é link")
        relativo = origem.relative_to(raiz).as_posix()
        if not (_OBJETO_SOLTO.match(relativo) or _OBJETO_PACK.match(relativo)):
            raise ErroSeguranca(
                f"quarentena contém {relativo!r}, que não tem forma de objeto "
                "de Git — promover nome arbitrário deixaria o repositório "
                "escrever caminho escolhido por ele dentro do store")
        destino = reais / relativo
        # O SUBDIRETÓRIO DE PREFIXO também é escolhido pelo repositório. MEDIDO
        # (P0): canonicalizar só o diretório `objects` deixa `<objects>/<2hex>`
        # livre — plantado como SYMLINK para fora, `mkdir(exist_ok=True)`,
        # `mkstemp(dir=...)` e `os.replace` seguem o link e gravam o objeto FORA
        # das raízes, no processo do supervisor, fora do sandbox. O irmão
        # `.git/objects` como link já era recusado; este é o nível abaixo, e o
        # ataque nem precisa prever o sha — 256 links de prefixo cobrem tudo.
        #
        # `canonicalizar` resolve os links do CAMINHO (existentes), então um
        # prefixo-symlink para fora cai fora de `permitida`. O diretório final
        # pode ainda não existir; o que importa é o link que já está no disco.
        if permitida:
            pai_real = supervisor.canonicalizar(str(destino.parent))
            if os.path.commonpath([pai_real, permitida]) != permitida:
                raise ErroSeguranca(
                    f"o diretório de prefixo do objeto resolve para "
                    f"{pai_real!r}, fora da raiz do store {permitida!r} — "
                    "`<objects>/<2hex>` como symlink faria a promoção gravar o "
                    "objeto fora das raízes, no processo do supervisor")
        pendentes.append((origem, destino))

    criados: list[Path] = []
    try:
        for origem, destino in pendentes:
            if destino.exists():
                # Endereçado por conteúdo: mesmo sha, mesmos bytes. Já existir é
                # deduplicação, não conflito — e NÃO entra em `criados`, porque
                # desfazer não pode apagar objeto que já era do store. Sem esta
                # distinção, uma falha posterior removeria do store um objeto
                # legítimo que não veio desta operação: corrupção causada pelo
                # próprio rollback.
                continue
            destino.parent.mkdir(parents=True, exist_ok=True)
            fd, temporario = tempfile.mkstemp(dir=destino.parent,
                                              prefix=".promovendo-")
            try:
                with os.fdopen(fd, "wb") as saida, open(origem, "rb") as ent:
                    shutil.copyfileobj(ent, saida)
                    saida.flush()
                    os.fsync(saida.fileno())
                os.chmod(temporario, 0o444)      # objeto de Git é imutável
                os.replace(temporario, destino)  # publicação ATÔMICA
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(temporario)
                raise
            criados.append(destino)
    except BaseException:
        # Desfaz na ordem inversa, e best-effort: um erro aqui não pode
        # sobrepor a exceção que trouxe o fluxo até este ponto.
        for feito in reversed(criados):
            with contextlib.suppress(OSError):
                feito.unlink()
        raise
    return len(criados)


class GitTreeAdapter(Adapter):
    """`git add` e `git commit`, confinados pelo supervisor."""

    capacidades = CAPACIDADES

    def __init__(self, binario: str | None = None,
                 identidade: Identidade | None = None,
                 registro: "filtro_governado.RegistroDeFiltros | None" = None):
        self._git = binario or "/usr/bin/git"
        self._id = identidade or Identidade()
        # Registry AUSENTE é diferente de registry VAZIO, e a diferença é de
        # comportamento: sem registry o adapter ignora `.gitattributes` por
        # completo (comportamento histórico, o filtro do repo já não executa);
        # com registry vazio, um pedido de filtro é RECUSADO por nome. Ausência
        # de política nunca vira fallback permissivo.
        self._registro = registro

    # -------------------------------------------------------------- ambiente

    def ambiente(self) -> dict[str, str]:
        """Ambiente mínimo do C1 mais a identidade, e nada além.

        `GIT_OPTIONAL_LOCKS=0` sai: aqui escrever o índice é o efeito desejado,
        e mantê-lo faria `add` recusar o próprio trabalho.
        """
        env = ambiente_minimo()
        env.pop("GIT_OPTIONAL_LOCKS", None)
        env.update({
            "GIT_AUTHOR_NAME": self._id.nome,
            "GIT_AUTHOR_EMAIL": self._id.email,
            "GIT_COMMITTER_NAME": self._id.nome,
            "GIT_COMMITTER_EMAIL": self._id.email,
        })
        return env

    # -------------------------------------------------------------- execução

    def executar(self, pedido: CapabilityRequest,
                 ctx: CapabilityContext) -> CapabilityResult:
        self._coerente(pedido, ctx)
        repo = resolver(texto_estrito(pedido.alvo, "alvo", obrigatorio=True),
                        ctx.raizes)
        # O `.exists()` que existia aqui era um ORÁCULO DE EXISTÊNCIA sobre
        # caminho ARBITRÁRIO do host (`N-A7-03`/`.1.N2`, resíduo de `.9.12`).
        # Ele SEGUE o symlink e responde ANTES de qualquer conferência de
        # raízes: com `.git` apontando para um caminho do host, a CLASSE da
        # exceção separava existente de ausente. MEDIDO em 12 caminhos —
        # 6 que existem e 6 que não — exatamente 2 classes de resposta, com
        # separação PERFEITA.
        #
        # E era redundante: `conferir_git_dir` logo abaixo já recusa o que não
        # é repositório, e recusa DEPOIS de confrontar o destino com as raízes.
        # Uma pré-checagem que só antecipa a mesma decisão, mas sem escopo, não
        # protege nada e vaza um bit por sonda.
        # A2-REPO: o `.git` do repositorio pode ser um ARQUIVO apontando o git
        # dir para fora das raizes aprovadas, e o git dir vira RAIZ DE ESCRITA
        # do sandbox. Conferir aqui, junto do `resolver`, porque e aqui que as
        # raizes existem — e antes de qualquer I/O que use o caminho.
        # BIND AUTHORITY: resolve+valida UMA vez e leva adiante. Antes, o
        # retorno era descartado e cada etapa relia `.git` do disco — TOCTOU
        # medido e EXPLORADO (corrida vencida 1/40 no push, com publicação de
        # repositório fora das raízes).
        gd, comum = conferir_git_dir(repo, ctx.raizes)
        autoridade = autoridade_de(repo, gd, comum)
        conferir_alternates(repo, ctx.raizes, autoridade)

        # `governados` viaja como ARGUMENTO até `_confirmar`, e não guardado no
        # adapter. Estado de operação em `self` faria duas operações
        # simultâneas no mesmo adapter trocarem de plano no meio — a `add` de um
        # repositório aplicando o filtro escolhido para outro.
        # O prazo é calculado ANTES do despacho porque `_add` agora PERGUNTA ao
        # Git quais caminhos pedem filtro (`check-attr`), e toda execução de
        # programa nesta série roda com prazo — inclusive a que só lê.
        prazo = min(TIMEOUT_S, ctx.restante() or TIMEOUT_S)
        if pedido.capacidade == "git-add":
            argv, descricao, governados, aprovados = self._add(
                pedido, repo, prazo, autoridade)
        elif pedido.capacidade == "git-commit":
            argv, descricao = self._commit(pedido, repo, prazo, autoridade)
            governados, aprovados = {}, []
        else:
            raise ErroInvalido(f"operação desconhecida: {pedido.capacidade}")

        # A partir daqui a operação é TRANSACIONAL: ou confirma, ou o índice
        # volta ao byte anterior. Detectar a falha e deixar o índice sujo era
        # detecção sem contenção — o `git add` já tinha estagiado o conteúdo
        # cru, e um `git commit` posterior persistiria o segredo mesmo com o
        # `add` tendo sido RECUSADO. O instantâneo é tirado ANTES do exec.
        instantaneo = _instantaneo_do_indice(repo, autoridade)
        # As REFS entram na transação, e a ausência delas era corrupção medida.
        # `git commit` avança `refs/heads/<b>` e escreve o reflog ANTES de o
        # `conferir_saida` recusar; os objetos do commit, porém, estão na
        # QUARENTENA, que o `finally` abaixo destrói. Resultado: `HEAD` e a ref
        # apontando para objeto INEXISTENTE — `git log` e `git status` param de
        # funcionar num repositório cuja operação foi RECUSADA.
        #
        # Restaurar o índice não alcançava isso: índice e refs são estados
        # diferentes, e a transação só cobria o primeiro.
        # Os caminhos JÁ estagiados, para a pós-condição de escopo distinguir
        # "o índice ganhou algo que ninguém aprovou" de "já estava lá".
        estagiados_antes = None
        if pedido.capacidade == "git-add":
            with contextlib.suppress(Exception):
                estagiados_antes = self._caminhos_estagiados(repo, prazo,
                                                             autoridade)
        refs = _instantaneo_das_refs(autoridade)
        split = _instantaneo_do_split(autoridade)
        quarentena, reais, fd_gd = _abrir_quarentena(repo, autoridade)
        raiz_q = Path(quarentena.diretorio)
        try:
            janela: dict = {}
            r = self._confirmar(pedido, ctx, repo, argv, descricao, prazo,
                                quarentena, governados, autoridade,
                                estagiados_antes, aprovados, janela)
        except BaseException as original:
            # BaseException, não Exception: KeyboardInterrupt e SystemExit
            # também não podem deixar segredo estagiado nem objeto no store.
            #
            # O desfazer NÃO pode substituir o erro que o causou. MEDIDO: com o
            # temporário do rollback inutilizável, o `IsADirectoryError` subia no
            # lugar do `ErroSeguranca`, e `isinstance(e, ErroSeguranca)` virava
            # False — qualquer chamador que classifique incidente de segurança
            # por tipo deixava de ver o incidente, que ficava só em
            # `__context__`. Mascarar a recusa é pior que a falha do rollback.
            #
            # A detecção de terceiro é LOCAL (retorno de `_restaurar_indice`),
            # não estado de módulo: `.8.07` mediu duas operações no mesmo
            # processo lendo/limpando a lista uma da outra.
            falhas: list[str] = []
            terceiro: list[str] = []
            # O DESFAZER GRAVA, e grava do processo do SUPERVISOR — fora do
            # sandbox. MEDIDO (`N-A7-02`, P0, 20/20): com `.git` trocado por
            # symlink depois do instantaneo, `_restaurar_indice` e
            # `_restaurar_refs` reconstruiram indice, refs e reflog DENTRO do
            # repositorio de terceiro (`ls-files` do git dir externo passou de
            # `DA_VITIMA.txt` para `DO_HOSTIL.txt`), e o NOMOS relatou a
            # operacao como RECUSADA. A recusa vinha DEPOIS do dano.
            #
            # Conferir a identidade antes de escrever transforma isso em
            # recusa-sem-efeito: se o objeto nao e mais o validado, nao ha
            # instantaneo que pertenca a ele, e desfazer seria escrever no
            # repositorio errado.
            if autoridade is not None:
                try:
                    autoridade.conferir_identidade("desfazer a operação")
                except ErroSeguranca as troca:
                    falhas.append(f"identidade: {troca}")
            # A quarentena some ANTES da montagem do aviso, para que um resíduo
            # entre no MESMO incidente. Deixá-la no `finally` fazia a limpeza
            # acontecer depois do `raise`, sem canal nenhum para relatar que o
            # store com o segredo continuava em disco (`.7.19`).
            residuo = _fechar_quarentena(raiz_q, fd_gd)
            depois = janela.get("idx_depois")
            antes = janela.get("idx_antes")
            # Fila VAZIA quando a identidade mudou: nao ha desfazer possivel
            # que caia no repositorio certo, e escrever seria o dano.
            etapas = () if falhas else (
                ("índice",
                 lambda: _restaurar_indice(instantaneo, depois, antes)),
                ("split index", lambda: _restaurar_split(split)),
                ("refs",
                 lambda: _restaurar_refs(refs, janela.get("refs_antes"),
                                         janela.get("refs_depois"))),
            )
            for etapa, fn in etapas:
                try:
                    # `índice` E `refs`: os dois desfazeres podem destruir
                    # trabalho de terceiro, e antes só o primeiro tinha canal —
                    # refs de outro processo sumiam em SILÊNCIO (`.6.N2`).
                    if fn() and etapa in ("índice", "refs"):
                        terceiro.append(etapa)
                except Exception as e:               # noqa: BLE001
                    falhas.append(f"{etapa}: {type(e).__name__}: {e}")
            # JANELA B: o que a comparação de BYTES não vê, o PATH-space viu.
            # `_conferir_escopo_estagiado` já identificou os caminhos que
            # entraram no índice e não são nossos; se houver, o desfazer os
            # sobrepôs — e sobrepor calado é o defeito (`.8.05-08`).
            de_terceiro = janela.get("caminhos_de_terceiro") or []
            if de_terceiro and "índice" not in terceiro:
                terceiro.append("índice")
            if falhas or terceiro or residuo:
                aviso = []
                if residuo:
                    # O resíduo é a quarentena INTEIRA, com o blob cru do
                    # arquivo recusado. Sem este canal, a recusa saía limpa e o
                    # segredo ficava legível por `git cat-file` no git dir.
                    aviso.append(
                        f"a QUARENTENA não pôde ser apagada ({residuo}) — o "
                        "conteúdo recusado pode ter ficado legível em "
                        f"{raiz_q}")
                if falhas:
                    aviso.append("o DESFAZER falhou em " + "; ".join(falhas)
                                 + " — o repositório pode ter ficado com o "
                                 "conteúdo recusado estagiado")
                if terceiro:
                    # QUAL estado, e não "o índice" para os dois: quem vai
                    # recuperar o trabalho perdido precisa saber onde procurar,
                    # e um aviso que diz "índice" quando o que sumiu foi uma
                    # REF manda a pessoa para o lugar errado.
                    quais = (f" (caminhos: {', '.join(de_terceiro[:5])})"
                             if de_terceiro else "")
                    aviso.append(
                        f"{' e '.join(terceiro)} — escrito por OUTRO processo "
                        "entre o instantâneo e o desfazer, e o rollback "
                        "sobrepôs esse trabalho: trabalho de terceiro foi "
                        f"perdido{quais}")
                # O TIPO do erro original é preservado, e isso é o ponto.
                # A primeira versão desta correção levantava `ErroSeguranca`
                # sempre — o que consertava o mascaramento medido em `.8.03` e
                # criava o MESMO defeito na direção oposta: um chamador que
                # classifica por `except RuntimeError` (ou `ErroFiltro`, ou
                # `ErroLimite`) deixava de ver o erro que realmente ocorreu.
                # A bateria A9 pegou: dois cenários injetam `RuntimeError` e
                # recebiam `ErroSeguranca`.
                #
                # Trocar o tipo é mascarar, mesmo mantendo o texto. O incidente
                # entra na MENSAGEM; a identidade da falha continua sendo a que
                # o chamador precisa para decidir.
                texto = f"{original}\n\nINCIDENTE NO DESFAZER: " + " | ".join(aviso)
                try:
                    novo = type(original)(texto)
                except Exception:                    # noqa: BLE001
                    # Exceção que não aceita um único argumento de texto: o
                    # original sobe intacto, e o incidente vai no `__notes__`
                    # em vez de sumir.
                    with contextlib.suppress(Exception):
                        original.add_note("INCIDENTE NO DESFAZER: "
                                          + " | ".join(aviso))
                    raise
                raise novo from original
            raise
        # A quarentena some nos DOIS caminhos. No sucesso ela já foi esvaziada
        # pela promoção (dentro de `_confirmar`, depois de TODAS as
        # verificações); na falha ela some cheia, levando junto o objeto que o
        # filtro gravou. Nunca `git gc`: isto apaga um diretório que só esta
        # execução escreveu, e nada mais.
        residuo = _fechar_quarentena(raiz_q, fd_gd)
        if residuo:
            # No SUCESSO o resíduo é vazio por construção (a promoção esvaziou),
            # então chegar aqui com sobra significa que alguém mexeu no git dir
            # durante a operação. Devolver `sucesso` com store paralelo em disco
            # seria a mesma omissão que `.7.19` mede, do outro lado.
            raise ErroSeguranca(
                f"a operação concluiu mas a QUARENTENA não pôde ser apagada "
                f"({residuo}): {raiz_q} continua no git dir. Um store paralelo "
                "sobrevivendo à operação é exatamente o que a quarentena existe "
                "para impedir")
        return r

    # ------------------------------------------------- A5.7 filtro governado

    def _caminhos_estagiados(self, repo: Path, prazo: float,
                             autoridade) -> set[str]:
        """Os caminhos que o índice tem AGORA, pelo próprio Git.

        Medir antes e depois com a MESMA pergunta evita reimplementar o formato
        do índice — e `GIT_INDEX_FILE` não serve para reler o instantâneo: a
        variável está em `PROIBIDAS_NO_AMBIENTE` (o supervisor recusa qualquer
        ambiente que a traga), justamente porque ela redireciona o índice.
        """
        p = supervisor.executar(
            self._base(repo) + ["ls-files", "-z"], cwd=repo,
            env=self.ambiente(), prazo=prazo,
            confinamento=confinamento_de_repo(repo, autoridade=autoridade),
            arvore_de_trabalho=str(repo))
        supervisor.conferir_sinal(p, "ls-files")
        if p.returncode != 0:
            raise ErroInvalido(
                f"não consegui listar o índice (rc={p.returncode})")
        return {c for c in p.stdout.decode("utf-8", "replace").split("\0") if c}

    def _conferir_escopo_estagiado(self, repo: Path, antes: set, aprovados,
                                   prazo: float, autoridade,
                                   janela: dict | None = None) -> None:
        """Pós-condição: o índice só pode ter ganhado o que foi APROVADO.

        MEDIDO (`.4.05b`), e é a razão de a checagem ser POSTERIOR: um
        pré-check nunca vence a corrida. `_recusar_diretorio` faz `os.lstat` no
        caminho, e o `git add` o REABRE PELO NOME muitos ms depois — trocar o
        arquivo por um DIRETÓRIO entre os dois fazia o Git expandir para tudo
        que estivesse dentro. 3/3 vitórias do atacante. É o mesmo
        resolve→valida→descarta→resolve-de-novo que `AutoridadeDeRepo` fechou
        em outro lugar; aqui o alvo é o NOME, que não dá para ligar a um
        descritor porque quem reabre é o Git.

        O que se pode amarrar é o EFEITO: comparar o índice antes e depois e
        exigir que todo caminho novo esteja na lista aprovada. A operação é
        transacional, então recusar aqui desfaz tudo — o escopo maior nunca
        chega a existir para o chamador.
        """
        if not aprovados or antes is None:
            return
        agora = self._caminhos_estagiados(repo, prazo, autoridade)
        candidatos = agora - antes - set(aprovados)

        # DISCRIMINADOR, e ele é o ponto: nem todo caminho novo é escopo maior.
        # MEDIDO — a primeira versão desta pós-condição recusava qualquer novo, e
        # com isso DESTRUÍA o trabalho de um `git add` concorrente que saiu com
        # rc=0 (o rollback o desfazia), quebrando exatamente a propriedade que
        # `.8.06` exige preservar. Duas exigências reais em conflito, resolvidas
        # pela ASSINATURA de cada uma:
        #
        #   expansão de diretório  -> o extra é DESCENDENTE de um aprovado
        #                             (`dir` vira `dir/x`, `dir/y`)
        #   escritor concorrente   -> o extra não tem relação com o aprovado
        #
        # Recusar só o primeiro contém o `-A` disfarçado sem destruir trabalho
        # de terceiro. O segundo já tem tratamento próprio: a detecção em
        # `_restaurar_indice`, que reporta o incidente em vez de silenciá-lo.
        prefixos = tuple(f"{a}/" for a in aprovados)
        novos = {c for c in candidatos if c.startswith(prefixos)}
        # A JANELA B em PATH-SPACE (`.8.05-08`, `.8.NEW-REFS-TERCEIRO`, P1).
        #
        # O canal de incidente de `_restaurar_indice` compara BYTES do índice, e
        # é por isso que ele enxerga as janelas A (instantâneo→foto de antes) e
        # C (foto de depois→desfazer) mas NÃO a B — a escrita de terceiro que
        # acontece DURANTE o nosso exec cai entre as duas fotos, junto com o
        # nosso próprio efeito, e as duas comparações dão "igual". MEDIDO 10/10
        # determinístico: o `git add` do terceiro saía rc=0, era aceito, e o
        # rollback o apagava sem emitir nada.
        #
        # Em BYTE-space não há como separar os dois. Em PATH-space há, e o dado
        # já está aqui: `candidatos` são os caminhos que apareceram no índice e
        # não são nossos (nem aprovados, nem descendentes deles). Reaproveitar
        # este conjunto não custa subprocesso novo — que importaria, porque cada
        # subprocesso a mais é mais uma superfície para morte por sinal sob
        # carga.
        terceiros = candidatos - novos
        if terceiros and janela is not None:
            janela["caminhos_de_terceiro"] = sorted(terceiros)
        if novos:
            raise ErroSeguranca(
                f"a operação estagiou caminho que NÃO foi aprovado: "
                f"{sorted(novos)[:5]} — o operador aprovou {sorted(aprovados)}. "
                "Um caminho que era arquivo na validação e virou DIRETÓRIO "
                "antes do `git add` faz o Git expandir para tudo que estiver "
                "dentro; a transação recusa e desfaz")

    def _recusar_diretorio(self, repo: Path, caminhos: list[str]) -> None:
        """Um DIRETÓRIO na lista é o `-A` disfarçado que este módulo proíbe.

        MEDIDO: `caminhos=['dir']` estagiou os TRÊS arquivos de `dir/`,
        inclusive `dir/NAO_APROVADO_segredo.txt`, e devolveu
        `valor='add 1 caminho(s)'` — a contagem relatada é a do PEDIDO, não a do
        efeito, então nem a auditoria mostrava o escopo real.

        `--no-all` não impede isso: ele governa o que acontece com arquivos
        REMOVIDOS, não a expansão de diretório. `_CAMINHO_PROIBIDO` já barra
        glob pelo mesmo motivo ("expande para o que existir no momento") — um
        diretório é o mesmo problema com outra sintaxe: entre a aprovação e a
        execução, qualquer arquivo que aparecer ali entra junto.

        `lstat` e não `is_dir()`: `is_dir()` SEGUE symlink, e um link para
        diretório passaria batido para virar exatamente o caso acima.
        """
        for caminho in caminhos:
            try:
                st = os.lstat(repo / caminho)
            except OSError:
                continue          # inexistente: quem recusa é o Git, com erro claro
            if stat.S_ISDIR(st.st_mode):
                raise ErroInvalido(
                    f"{caminho!r} é um DIRETÓRIO, e diretório expande para tudo "
                    "que estiver dentro dele no momento da execução — é o `-A` "
                    "disfarçado. O operador aprova uma lista de ARQUIVOS: "
                    "nomeie cada um")

    def _recusar_fonte_de_atributo_por_link(self, repo: Path,
                                            caminhos: list[str],
                                            autoridade=None) -> None:
        """Nenhuma fonte de atributo do repositório pode ser SYMLINK.

        MEDIDO (C2.11): com `.gitattributes` apontando para fora das raízes, a
        política que decide se o segredo é redigido passa a morar num arquivo
        que ninguém aprovou. E o desfecho é o pior possível: dentro do sandbox o
        Git não CONSEGUE ler o destino, então não vê pedido de filtro nenhum,
        indexa o conteúdo CRU e devolve rc=0. O atacante que quer o segredo em
        claro só precisa trocar o arquivo de regras por um link.

        Recusar é estreito e correto: symlink não é forma legítima de declarar
        atributo, e a mensagem diz o que fazer (arquivo regular).
        """
        # Fontes na WORKING TREE (relativas ao repo) e no GIT DIR. O git dir vem
        # da AUTORIDADE, não do literal `<repo>/.git`: em worktree ligada e
        # submódulo o `info/attributes` efetivo mora noutro lugar, e conferir o
        # caminho errado é não conferir.
        raizes_fontes = self._fontes_de_atributo(repo, caminhos, autoridade)
        vistos: set[str] = set()
        for base, componentes in raizes_fontes:
            chave = str(base) + "/" + "/".join(componentes)
            if chave in vistos:
                continue
            vistos.add(chave)
            self._recusar_componente_link(base, componentes)

    def _fontes_de_atributo(self, repo: Path, caminhos: list[str],
                            autoridade=None) -> list[tuple[Path, list[str]]]:
        """Toda fonte de atributo que o Git consultaria para estes caminhos."""
        raizes_fontes: list[tuple[Path, list[str]]] = []
        for caminho in caminhos:
            pai = PurePosixPath(caminho).parent
            partes = [] if str(pai) == "." else list(pai.parts)
            for i in range(len(partes) + 1):
                raizes_fontes.append((repo, [*partes[:i], ".gitattributes"]))
        gd = Path(autoridade.git_dir) if autoridade is not None else repo / ".git"
        raizes_fontes.append((gd, ["info", "attributes"]))
        # E o COMMON DIR. MEDIDO (`.2.15`, P0): em WORKTREE LIGADA o Git lê
        # `info/attributes` do COMMON — o per-worktree é IGNORADO. Conferir só
        # o git dir era conferir um arquivo que o Git nem lê, e um symlink em
        # `<common>/info/attributes` (ou `<common>/info` como link de diretório)
        # fazia o pedido de filtro DESAPARECER: segredo EM CLARO no índice e no
        # store permanente, com ok=True, enquanto o git cru redige.
        #
        # A suíte C2 inteira roda em repo simples, onde `git_dir == common` e o
        # furo é invisível — 15/15 verdes com ele presente.
        if autoridade is not None and autoridade.common != autoridade.git_dir:
            raizes_fontes.append((Path(autoridade.common),
                                  ["info", "attributes"]))
        return raizes_fontes

    def _cancelamento_declarado(self, repo: Path, caminhos: list[str],
                                autoridade=None) -> str:
        """Nenhuma fonte de atributo pode CANCELAR um filtro governado.

        MEDIDO, e é a segunda forma do mesmo ataque: `-filter` faz `check-attr`
        responder `unset`, e `!filter` faz responder `unspecified` — mas os DOIS
        cancelam a regra de redação da fonte de menor precedência. Com a
        cancelação, o índice fica `SENHA=hunter2`; sem ela, `SENHA=REDIGIDO`.

        A defesa anterior tratava só `unset`, e por isso `!filter` a contornava
        trocando um token por outro. E `unspecified` sozinho NÃO serve de
        critério: ele também é a resposta legítima de "não há regra nenhuma".

        Por que não voltar a interpretar padrão: essa é exatamente a classe de
        divergência que `check-attr` veio eliminar. Aqui NÃO se decide a QUEM a
        regra se aplica — recusa-se a EXISTÊNCIA de um cancelamento de filtro em
        qualquer fonte que este repositório declare. Num repositório com filtro
        governado, cancelar redação não é necessidade legítima; é o pedido para
        publicar o segredo em claro.
        """
        for base, componentes in self._fontes_de_atributo(repo, caminhos,
                                                          autoridade):
            alvo = base.joinpath(*componentes)
            try:
                st = os.lstat(alvo)
                if not stat.S_ISREG(st.st_mode):
                    continue
                # TETO DE 100 MiB, e ele é do GIT (`.2.N9-ATTRS-ACIMA-DO-TETO`,
                # P0). MEDIDO no Git 2.50.1: uma fonte de atributo acima de
                # `ATTR_MAX_FILE_SIZE` é IGNORADA em silêncio, com
                # `warning: ignoring overly large gitattributes file` e rc=0 —
                # mensagem que o guard de `.2.15` não casa (ele exige "unable
                # to access") e que `conferir_saida` não vê (casa `^(error|
                # fatal):`). Discriminante: 99 MiB -> REDIGIDO, 101 MiB -> EM
                # CLARO. O repositório escolhe o TAMANHO, e com ele escolhe se
                # a redação acontece.
                if st.st_size > ATTR_MAX_GIT:
                    raise ErroSeguranca(
                        f"a fonte de atributo {alvo} tem {st.st_size} bytes, "
                        f"acima do teto do próprio Git ({ATTR_MAX_GIT}). Acima "
                        "dele o Git IGNORA o arquivo com um `warning:` e rc=0 — "
                        "toda regra de redação declarada ali desaparece em "
                        "silêncio, e o conteúdo entra EM CLARO no índice")
                # E o teto DESTA leitura, que roda no processo do SUPERVISOR,
                # fora do sandbox (`.2.N8` / `.9.NOVO-ATTR-ILIMITADA`): antes era
                # `read_text()` sem limite nenhum, guiado pelo repositório. O
                # contraste estava no mesmo arquivo — o conteúdo FILTRADO já tem
                # `MAX_CONTEUDO`. Os dois ramos da mesma função com garantias
                # opostas é a forma exata de `.9.11`.
                with open(alvo, "rb") as fh:
                    texto = fh.read(ATTR_MAX_GIT).decode("utf-8", "replace")
            except OSError:
                continue
            for linha in texto.splitlines():
                corpo = linha.split("#", 1)[0]
                # POR TOKEN, e não por substring (`.2.N1` P0 e `.2.N6` P2).
                # MEDIDO: o Git separa atributo por QUALQUER `isspace()`, então
                # `SEGREDO.txt\t!filter` cancela igual — e a busca por
                # `" !filter"` (espaço + token) não via. Na direção oposta,
                # `" -filter"` casava `-filterset`, um atributo SEM relação com
                # `filter`, e recusava a operação inteira.
                #
                # `split()` sem argumento separa por qualquer espaço em branco,
                # que é a mesma regra do Git. O primeiro token é o PADRÃO; os
                # demais são atributos.
                tokens = corpo.split()
                if any(t in ("-filter", "!filter") for t in tokens[1:]):
                    # NAO recusa aqui: quem sabe se o cancelamento ALCANCA os
                    # caminhos pedidos e o `check-attr`, e a resposta dele vem
                    # depois. Recusar por EXISTENCIA recusava `*.png -filter`,
                    # que e o uso mais comum e mais legitimo de `-filter`
                    # (`.2.N7`). Aqui so se reporta que existe.
                    return f"{alvo}: {linha.strip()!r}"
        return ""

    def _recusar_componente_link(self, base: Path, componentes: list[str]) -> None:
        """Nenhum COMPONENTE do caminho da fonte pode ser symlink.

        MEDIDO (`.2.14`, P0), e é o furo que o `lstat` do último componente não
        via: trocando o DIRETÓRIO `.git/info` por um symlink para fora das
        raízes de LEITURA do sandbox, `os.lstat('.git/info/attributes')`
        atravessa o `info` do meio e enxerga arquivo REGULAR — a guarda não
        dispara. Dentro do sandbox o Git não consegue ler o destino, então o
        pedido de filtro DESAPARECE e o segredo entra EM CLARO no índice com
        `ok=True`, enquanto o git cru continua redigindo. Divergência a MENOS de
        segurança que o Git, que é exatamente o que a bateria C2 existe para
        impedir.

        Descer com `openat`/`O_NOFOLLOW` a cada componente é a mesma técnica de
        `_abrir_sem_atravessar_link` — e pela mesma razão: `O_NOFOLLOW` protege
        só o último nome.
        """
        try:
            fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY)
        except OSError:
            return
        try:
            for i, nome in enumerate(componentes):
                ultimo = i == len(componentes) - 1
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                if not ultimo:
                    flags |= os.O_DIRECTORY
                try:
                    proximo = os.open(nome, flags, dir_fd=fd)
                except OSError as e:
                    if e.errno in (errno.ELOOP, errno.EMLINK, errno.ENOTDIR):
                        rel = "/".join(componentes[:i + 1])
                        raise ErroSeguranca(
                            f"{rel} é um symlink, e fonte de atributo não pode "
                            "ser link: quem escolhe o destino escolhe a política "
                            "de filtro, e um destino fora das raízes o Git nem "
                            "consegue ler dentro do sandbox — o pedido de filtro "
                            "sumiria e o conteúdo seria indexado EM CLARO com "
                            "rc=0") from None
                    return          # ausente: não há fonte a conferir
                if ultimo:
                    os.close(proximo)
                    return
                os.close(fd)
                fd = proximo
        finally:
            with contextlib.suppress(OSError):
                os.close(fd)

    def _config_do_repo(self, repo: Path, prazo: float,
                        autoridade) -> dict[str, str]:
        """TODA a config efetiva do repositório, numa ÚNICA execução.

        `--list` resolve `include.path` — MEDIDO (`.2.N3`): tanto `attr.tree`
        quanto `core.attributesFile` plantados por include são honrados pelo
        Git E aparecem aqui, então a detecção não é contornável escondendo a
        chave num arquivo incluído.

        UMA chamada e não duas, por medição: cada subprocesso no caminho
        governado é mais uma superfície para morte por SIGKILL sob carga, e a
        bateria de corrida cobrou isso — `git config foi encerrado por sinal
        (rc=-9)` derrubou `test_a9_03` depois que este guard passou a rodar.
        O produto classificou certo (fail-closed); o custo é que a janela
        existe, e metade dela era evitável.

        As chaves vêm em CAIXA BAIXA do `--list`, que é como o Git as compara.
        """
        # `_base` NÃO entra aqui, e isso é a correção de um defeito que eu
        # mesmo introduzi ao colapsar duas chamadas em uma. MEDIDO: `_base`
        # injeta `-c core.attributesFile=` (a neutralização de `_NEUTRALIZAR_TREE`),
        # e `--list` emite AS DUAS ocorrências — a do repositório e a vazia.
        # Guardando a última (regra do Git: a última vence), o valor efetivo é
        # `""` e a detecção morria: `test_c2_11` deixou de recusar
        # `core.attributesFile`. O `--get-all` anterior não sofria disso porque
        # o `-c` não estava no argv dele.
        #
        # O que se quer aqui não é o valor EFETIVO — é a DECLARAÇÃO do
        # repositório. Por isso o argv é mínimo e sem neutralização: o
        # `--list` puro mostra o que o repositório escreveu, que é exatamente
        # sobre o que a política decide.
        argv = [self._git, "-C", str(repo), "--no-pager", "config", "--list"]
        p = supervisor.executar(
            argv, cwd=repo, env=self.ambiente(), prazo=prazo,
            confinamento=confinamento_de_leitura(repo, autoridade),
            arvore_de_trabalho=str(repo))
        # Morte por SINAL não é erro de sintaxe — a MESMA armadilha de `.6.10`,
        # neste outro caminho (`.11.12`). Corrigir num lugar e deixar o irmão
        # foi o que a medição pegou.
        if p.morto_por_timeout or p.returncode < 0:
            raise ErroLimite(
                f"git config foi encerrado por sinal (rc={p.returncode})"
                f"{' após o prazo' if p.morto_por_timeout else ''} — sem "
                "resposta não dá para saber que fontes de atributo o "
                "repositório declara, e seguir seria indexar sem conhecer a "
                "política")
        # rc=1 é "config vazia", o caso normal. rc>1 é erro de verdade.
        if p.returncode not in (0, 1):
            erro = p.stderr.decode("utf-8", "replace")[:400]
            raise ErroInvalido(f"git config falhou (rc={p.returncode}): {erro}")
        mapa: dict[str, str] = {}
        for linha in p.stdout.decode("utf-8", "replace").splitlines():
            chave, sep, valor = linha.partition("=")
            if sep:
                mapa[chave.strip().lower()] = valor.strip()
        return mapa

    def _recusar_fonte_de_atributo_externa(self, repo: Path, prazo: float,
                                           autoridade) -> None:
        """Fonte de atributo que o disk-scan não alcança é RECUSA, não no-op.

        Duas chaves do REPOSITÓRIO reapontam a fonte de atributos para fora do
        alcance de `_recusar_cancelamento_de_filtro` (que varre ARQUIVOS):

            core.attributesFile   um arquivo FORA do repositório
            attr.tree             uma ÁRVORE Git (`.2.N3`, P0)

        `core.attributesFile`: dentro do sandbox o destino não é legível — nem
        pelo `check-attr`, nem pelo `add`. Os dois concordam em não ver pedido
        de filtro, e o conteúdo é indexado CRU com rc=0.

        `attr.tree`: MEDIDO, e é a razão de esta recusa existir. Com a árvore
        apontada, `git check-attr filter` responde `unspecified` para um
        `!filter` que MORA na árvore — indistinguível de "não há regra", que é
        a resposta legítima e comum. Não há como o Git DISTINGUIR os dois na
        saída, então a autoridade que `_pedidos_de_filtro` delega ao Git fica
        cega justamente aqui: o segredo entra EM CLARO com ok=True. E a
        neutralização não salva — `attr.tree` REESCREVE a fonte (não acumula),
        então `-c attr.tree=<vazio>` restaura o working tree mas
        `-c attr.tree=<árvore-vazia>` APAGA também a regra de redação legítima.
        `attr.source` NÃO é chave de config (medido: sem efeito); o vetor é
        `attr.tree`, e ele é o único.

        Por que RECUSAR e não varrer a árvore: varrer exigiria reimplementar a
        precedência de atributos por diretório que o Git resolve — o parser que
        esta série documenta NÃO manter (l. 1485-1489). Fonte que o Git resolve
        de um jeito que a saída não deixa auditar é fonte que a política não
        consegue provar; fail-closed é a resposta. O caminho legítimo declara
        os atributos no `.gitattributes` da working tree ou em
        `.git/info/attributes`, que o disk-scan alcança.
        """
        cfg = self._config_do_repo(repo, prazo, autoridade)
        if cfg.get("core.attributesfile"):
            raise ErroSeguranca(
                "o repositório declara `core.attributesFile`, que põe a fonte "
                "de atributos FORA do repositório. Dentro do sandbox esse "
                "arquivo não é legível, então o pedido de filtro desapareceria "
                "e o conteúdo seria indexado EM CLARO com rc=0 — recuso em vez "
                "de ignorar em silêncio. Declare os atributos no próprio "
                "repositório (`.gitattributes` ou `.git/info/attributes`)")
        if cfg.get("attr.tree"):
            raise ErroSeguranca(
                "o repositório declara `attr.tree`, que lê os atributos de uma "
                "ÁRVORE Git em vez da working tree. Um `!filter` plantado nessa "
                "árvore CANCELA a redação e o `check-attr` responde "
                "`unspecified` — indistinguível de 'não há regra'. A varredura "
                "de disco não alcança a árvore, e a resposta do Git não deixa "
                "auditar: recuso em vez de indexar EM CLARO. Declare os "
                "atributos no `.gitattributes` da working tree")

    def _pedidos_de_filtro(self, repo: Path, caminhos: list[str],
                           prazo: float, autoridade) -> dict[str, str]:
        """`{caminho: filter_id PEDIDO}` — decidido pelo GIT, não por nós.

        ## Por que não um parser próprio

        A versão anterior lia `repo/.gitattributes` e casava padrão com
        `fnmatch`. A bateria A2-REPO mediu OITO formas idiomáticas em que o Git
        aplica um filtro e esse parser não via nada — e a consequência não é
        "filtro não aplicado", é **segredo indexado EM CLARO com `ok=True`**,
        que é exatamente o modo de falha que esta série existe para eliminar:

            .gitattributes em SUBDIRETÓRIO          (o Git usa o mais próximo)
            padrão ancorado `/SEGREDO.txt`
            macro `[attr]zz filter=…` + `SEGREDO.txt zz`
            padrão entre aspas `"SEGREDO.txt"`
            `.git/info/attributes`                  (precedência MAIOR)
            `core.attributesFile` fora do repositório
            `attr.tree=HEAD`                        (atributos de uma ÁRVORE)
            divergência de CAIXA sob `core.ignorecase`

        Cada uma dessas é um bug de parser diferente, e a lista não fecha: a
        semântica de atributos é do Git e muda com ele. Corrigir oito casos
        deixaria o nono aberto.

        Quem sabe responder "este caminho pede filtro?" é o próprio Git.
        `check-attr` roda com o MESMO argv base (`_base`), o MESMO ambiente e a
        MESMA working tree pinada do `add` que vem depois — então os dois
        enxergam as mesmas fontes de atributo por construção, e não por uma
        tabela que alguém precisa manter sincronizada.

        MEDIDO e decisivo para a escolha: `-c attr.tree=` NÃO desliga
        `attr.tree` (o Git segue lendo a árvore). É a mesma armadilha de
        `core.worktree` — neutralização por linha de comando que parece
        funcionar e é no-op. Uma defesa baseada em neutralizar chaves ficaria
        silenciosamente furada; perguntar ao Git não depende de nenhuma delas.

        O `filter_id` continua sendo entrada NÃO CONFIÁVEL: passa por
        `conferir_id` antes de virar consulta ao registry, e id desconhecido é
        DENY. O que o repositório ganha é escolher ENTRE os filtros já
        aprovados — nunca introduzir um.
        """
        from nomos.adapters import filtro_governado as fg

        self._recusar_fonte_de_atributo_por_link(repo, caminhos, autoridade)
        cancelamento = self._cancelamento_declarado(repo, caminhos, autoridade)
        self._recusar_fonte_de_atributo_externa(repo, prazo, autoridade)

        argv = self._base(repo) + ["check-attr", "-z", "filter", "--", *caminhos]
        p = supervisor.executar(
            argv, cwd=repo, env=self.ambiente(), prazo=prazo,
            confinamento=confinamento_de_leitura(repo, autoridade),
            arvore_de_trabalho=str(repo))
        if p.morto_por_timeout:
            raise ErroLimite(
                "check-attr excedeu o prazo — sem a resposta do Git não dá "
                "para saber se um caminho pede filtro, e seguir seria indexar "
                "conteúdo cru sem saber")
        supervisor.conferir_sinal(p, "check-attr")
        if p.returncode != 0:
            erro = p.stderr.decode("utf-8", "replace")[:400]
            raise ErroInvalido(f"check-attr falhou (rc={p.returncode}): {erro}")
        supervisor.conferir_saida(p.stderr, "git-add")
        # `conferir_saida` casa `^(error|fatal):` de propósito, e por isso NÃO
        # vê `warning: unable to access '<...>/info/attributes'`. MEDIDO
        # (`.2.15`): o check-attr saiu rc=0, com esse aviso no stderr, e o
        # pedido de filtro tinha simplesmente sumido — o sinal existia e foi
        # engolido, e o `git add` seguinte saiu rc=0 com stderr VAZIO.
        #
        # Aqui o aviso é FATAL por natureza: se o Git não conseguiu LER uma
        # fonte de atributo, a resposta do `check-attr` é incompleta, e seguir
        # com ela é indexar conteúdo cru sem saber que havia regra.
        erro_txt = p.stderr.decode("utf-8", "replace")
        if "unable to access" in erro_txt and "attributes" in erro_txt:
            raise ErroSeguranca(
                "o Git não conseguiu LER uma fonte de atributo dentro do "
                f"sandbox: {erro_txt.strip()[:200]}. A resposta do `check-attr` "
                "fica incompleta e o pedido de filtro desaparece em silêncio — "
                "seguir indexaria o conteúdo CRU sem saber que havia regra")

        campos = p.stdout.decode("utf-8", "replace").split("\0")
        # `-z` emite trincas <caminho>\0<atributo>\0<valor>\0; a cauda depois do
        # último NUL é vazia e não é registro.
        if len(campos) % 3 == 1 and campos[-1] == "":
            campos = campos[:-1]
        if len(campos) % 3:
            raise ErroInvalido(
                f"check-attr devolveu {len(campos)} campos, que não formam "
                "trincas <caminho, atributo, valor> — recuso em vez de adivinhar")
        if len(campos) // 3 > MAX_ATRIBUTOS:
            raise ErroLimite(
                f"check-attr devolveu {len(campos) // 3} registros (limite "
                f"{MAX_ATRIBUTOS})")

        pedidos: dict[str, str] = {}
        for i in range(0, len(campos), 3):
            caminho, _atributo, valor = campos[i], campos[i + 1], campos[i + 2]
            # `unspecified` = NÃO HÁ regra. `set` = o atributo existe sem nomear
            # driver. Nenhum dos dois é pedido de filtro, e nenhum dos dois
            # exige decisão.
            if valor == "unspecified" and cancelamento:
                # `unspecified` e AMBIGUO: e a resposta de "nao ha regra" E a de
                # `!filter` (`.2.N1`). O `check-attr` nao distingue as duas na
                # saida — mas se alguma fonte DECLARA cancelamento e ESTE
                # caminho vem sem filtro, a coincidencia e o ataque.
                #
                # Cruzar os dois sinais e o que separa `.2.N1` de `.2.N7`: com
                # `*.png -filter` e o pedido em `segredo.txt`, o check-attr
                # responde `redator` e nao chega aqui — o cancelamento existe,
                # mas nao ALCANCA o caminho pedido, e recusar seria recusa falsa
                # do uso mais legitimo que `-filter` tem.
                raise ErroSeguranca(
                    f"o caminho {caminho!r} vem SEM filtro do `check-attr` e o "
                    f"repositorio DECLARA cancelamento em {cancelamento}. "
                    "`!filter` e `-filter` desligam a regra de redacao de uma "
                    "fonte de menor precedencia, e `unspecified` e a MESMA "
                    "resposta que o Git da para 'nao ha regra' — nao da para "
                    "distinguir pela saida. Recuso em vez de indexar EM CLARO. "
                    "Remova o cancelamento ou declare o filtro governado")
            if valor in ("unspecified", "set"):
                continue
            # `unset` é DIFERENTE, e a diferença é o achado (`.2.13`): ele só
            # existe porque alguém escreveu `-filter` — um CANCELAMENTO
            # EXPLÍCITO. Uma fonte de atributo de precedência maior (o
            # `.gitattributes` de um subdiretório, ou `.git/info/attributes`)
            # cancela a regra da raiz, e o segredo entra EM CLARO no índice com
            # `ok=True` e sem nenhum sinal ao operador.
            #
            # Não há divergência contra o git cru — ele faz o mesmo — mas a
            # propriedade que esta série sustenta não é paridade com o Git, é
            # "o repositório não escolhe se o segredo é redigido". Tratar
            # cancelamento explícito como ausência de regra é a mesma falha
            # silenciosa de `core.attributesFile`, e a resposta é a mesma:
            # recusar em vez de ignorar em silêncio.
            if valor == "unset":
                raise ErroSeguranca(
                    f"o repositório CANCELA o filtro de {caminho!r} com "
                    "`-filter` numa fonte de atributo de precedência maior. "
                    "Cancelamento explícito não é ausência de regra: seguir "
                    "indexaria o conteúdo EM CLARO com rc=0, e quem aprovou a "
                    "operação não saberia. Remova o `-filter` ou declare o "
                    "filtro governado que deve valer")
            if caminho not in caminhos:
                raise ErroSeguranca(
                    f"check-attr respondeu sobre {caminho!r}, que não está "
                    "entre os caminhos pedidos")
            pedidos[caminho] = fg.conferir_id(valor)
        return pedidos

    def _aplicar_filtro_governado(self, repo: Path, caminho: str,
                                  filter_id: str, prazo: float,
                                  quarentena: supervisor.Quarentena,
                                  autoridade=None) -> str:
        """PEDIDO → política → artefato → argv → sandbox → stdin → índice.

        Devolve o sha do blob TRANSFORMADO, já gravado na quarentena. Nada aqui
        toca o store permanente: a promoção é a última coisa da transação, e
        acontece só se a operação inteira for aceita.
        """
        politica = self._registro.resolver(filter_id)   # id desconhecido = DENY

        bruto = _ler_alvo_do_filtro(repo, caminho)

        p = supervisor.executar(
            politica.comando(), cwd=repo, env=politica.ambiente(),
            prazo=min(politica.timeout, prazo),
            confinamento=politica.confinamento(),
            tipo=supervisor.TipoDeProcesso.FILTRO_GOVERNADO, entrada=bruto)
        if p.morto_por_timeout:
            raise ErroLimite(
                f"filtro governado {filter_id!r} excedeu o prazo em {caminho} "
                "e a árvore de processos foi encerrada")
        supervisor.conferir_sinal(p, f"filtro governado {filter_id!r}")
        if p.returncode != 0:
            erro = p.stderr.decode("utf-8", "replace")[:400]
            raise ErroInvalido(
                f"filtro governado {filter_id!r} falhou em {caminho} "
                f"(rc={p.returncode}): {erro}")

        # `--no-filters` é o ponto da coisa toda: o conteúdo que entra no
        # objeto é o que SAIU do filtro governado, e o Git não tem chance de
        # aplicar por cima o `filter.<id>.clean` que o repositório declarou.
        # Sem esta flag, a transformação do NOMOS seria a entrada do filtro do
        # repo — o inverso exato do que A5 decidiu.
        h = supervisor.executar(
            self._base(repo) + ["hash-object", "-w", "--no-filters", "--stdin"],
            cwd=repo, env=self.ambiente(), prazo=prazo,
            confinamento=confinamento_de_repo(repo, autoridade=autoridade),
            quarentena=quarentena,
            entrada=p.stdout, arvore_de_trabalho=str(repo))
        supervisor.conferir_sinal(h, f"hash-object em {caminho}")
        if h.returncode != 0:
            erro = h.stderr.decode("utf-8", "replace")[:400]
            raise ErroInvalido(f"hash-object falhou em {caminho}: {erro}")
        supervisor.conferir_saida(h.stderr, "git-add")
        sha = h.stdout.decode().strip()
        if not re.fullmatch(r"[0-9a-f]{40,64}", sha):
            raise ErroInvalido(
                f"hash-object devolveu {sha[:80]!r}, que não é um sha — recuso "
                "em vez de estagiar um identificador que não sei o que é")
        return sha

    def _estagiar(self, repo: Path, caminho: str, sha: str, prazo: float,
                  quarentena: supervisor.Quarentena, autoridade=None) -> None:
        """Põe o blob transformado no índice, sem passar pela working tree."""
        modo = "100755" if os.access(repo / caminho, os.X_OK) else "100644"
        u = supervisor.executar(
            self._base(repo) + ["update-index", "--add", "--cacheinfo",
                                f"{modo},{sha},{caminho}"],
            cwd=repo, env=self.ambiente(), prazo=prazo,
            confinamento=confinamento_de_repo(repo, autoridade=autoridade),
            quarentena=quarentena,
            arvore_de_trabalho=str(repo))
        supervisor.conferir_sinal(u, f"update-index em {caminho}")
        if u.returncode != 0:
            erro = u.stderr.decode("utf-8", "replace")[:400]
            raise ErroInvalido(f"update-index falhou em {caminho}: {erro}")
        supervisor.conferir_saida(u.stderr, "git-add")

    def _confirmar(self, pedido, ctx, repo: Path, argv: list[str],
                   descricao: str, prazo: float,
                   quarentena: supervisor.Quarentena,
                   governados: dict[str, str],
                   autoridade, estagiados_antes=None,
                   aprovados: list[str] | None = None,
                   janela: dict | None = None) -> CapabilityResult:
        """Executa e valida. Qualquer saída por exceção desfaz o índice.

        A promoção dos objetos acontece DEPOIS de todas as verificações: um
        objeto só chega ao store permanente quando a operação inteira foi
        aceita. É isso que impede o segredo de um filtro quebrado de existir
        fora da quarentena, em vez de apagá-lo depois de gravado.
        """
        # AS FOTOS ENQUADRAM TODOS OS NOSSOS EFEITOS, não só o exec (`.11.09`).
        #
        # MEDIDO 8/8 com gatilho REAL do repositório: `_estagiar` (logo abaixo)
        # já reescreve o índice, e o ramo TODOS-GOVERNADOS retorna ANTES de
        # `janela` ser populada. Aí `idx_antes`/`idx_depois` ficam None, o
        # desfazer cai no fallback `esperado = dados` (o instantâneo
        # PRÉ-OPERAÇÃO) e acusa como TERCEIRO exatamente o efeito que NÓS
        # acabamos de aplicar — incidente forense falso, sem concorrência
        # nenhuma. É o mesmo defeito de `.11.09` no ramo que ninguém olhou.
        #
        # A foto de ANTES sobe para cá: o que ela ainda não vê e o desfazer
        # encontra é nosso; o que ela JÁ vê divergindo do instantâneo é de outro
        # processo. Vale para os DOIS ramos, com exec e sem.
        alvo_idx = Path(autoridade.git_dir) / "index" if autoridade else None
        if janela is not None and not janela:
            janela["refs_antes"] = _refs_agora(autoridade)
            if alvo_idx is not None and alvo_idx.exists():
                with contextlib.suppress(OSError):
                    janela["idx_antes"] = alvo_idx.read_bytes()

        for caminho, filter_id in governados.items():
            sha = self._aplicar_filtro_governado(repo, caminho, filter_id,
                                                 prazo, quarentena, autoridade)
            self._estagiar(repo, caminho, sha, prazo, quarentena, autoridade)
        if governados and not argv:
            # Ramo TODOS-GOVERNADOS: não há exec, mas HOUVE efeito nosso (o
            # `_estagiar` acima). A foto de DEPOIS tem de ser tirada aqui, senão
            # o desfazer de uma falha na auditoria ou na promoção — que vêm
            # logo abaixo — culpa terceiro pelo nosso próprio estagiamento.
            if janela is not None and alvo_idx is not None and alvo_idx.exists():
                with contextlib.suppress(OSError):
                    janela["idx_depois"] = alvo_idx.read_bytes()
                janela["refs_depois"] = _refs_agora(autoridade)
            # TODOS os caminhos eram governados: não sobrou `git add` para
            # rodar, e inventar um rodaria o Git sobre a working tree CRUA —
            # desfazendo, no último passo, a transformação que acabou de ser
            # aplicada.
            self._auditar(ctx, "git.add",
                          alvo=supervisor.canonicalizar(repo),
                          **_campos_de_autoridade(autoridade),
                          detalhe=descricao, sandbox=True, rede=False,
                          classificacao="EXIT_OK", morto_por_timeout=False)
            _promover_quarentena(Path(quarentena.diretorio),
                                 Path(quarentena.alternativos),
                                 raiz_do_store=autoridade.common)
            return CapabilityResult.sucesso(descricao, efeito_aplicado=True)

        # A foto de ANTES já foi tirada no TOPO deste método, e é lá que ela tem
        # de ficar: se fosse retirada aqui, o `_estagiar` dos caminhos
        # governados (que roda acima, no caminho MISTO) já teria entrado nela, e
        # o nosso próprio efeito passaria a contar como estado pré-existente.
        # Retirá-la de novo aqui SOBRESCREVERIA a foto correta.
        p = supervisor.executar(argv, cwd=repo, env=self.ambiente(),
                                prazo=prazo,
                                confinamento=confinamento_de_repo(
                                    repo, autoridade=autoridade),
                                quarentena=quarentena,
                                arvore_de_trabalho=str(repo))
        if janela is not None:
            janela["refs_depois"] = _refs_agora(autoridade)
        # O índice LOGO APÓS o exec, e ANTES de qualquer `raise`. MEDIDO
        # (`.6.N1`): capturar depois do check de `returncode` deixava o baseline
        # VAZIO justamente nas recusas — o git rodou, reescreveu o índice, e
        # falhou. Aí o detector caía de volta no instantâneo e acusava
        # "trabalho de terceiro foi perdido" sem terceiro nenhum. Basta o
        # repositório plantar `.git/refs/heads` como symlink de diretório para
        # provocar um INCIDENTE FORENSE FALSO, sozinho e sem concorrência.
        if janela is not None and alvo_idx is not None and alvo_idx.exists():
            with contextlib.suppress(OSError):
                janela["idx_depois"] = alvo_idx.read_bytes()
        if p.morto_por_timeout:
            # O filtro do repositório pendura o processo — medido, não suposto.
            # A árvore inteira já morreu; o que resta é recusar.
            raise ErroLimite(
                f"{pedido.capacidade} excedeu {prazo:.1f}s e a árvore de "
                "processos foi encerrada (provável filtro do repositório)")
        supervisor.conferir_sinal(p, pedido.capacidade)
        if p.returncode != 0:
            erro = p.stderr.decode("utf-8", "replace")[:400]
            raise ErroInvalido(
                f"{pedido.capacidade} falhou (rc={p.returncode}): {erro}")
        # `git add` é a ÚNICA capacidade que roda programa do repositório (o
        # filtro). É também onde o rc=0 mente com mais consequência: filtro
        # quebrado indexa o conteúdo cru. Aqui a mentira para.
        supervisor.conferir_saida(p.stderr, pedido.capacidade)
        if pedido.capacidade == "git-add":
            self._conferir_escopo_estagiado(repo, estagiados_antes, aprovados,
                                            prazo, autoridade, janela)
        self._auditar(ctx, f"git.{pedido.capacidade[4:]}",
                      alvo=supervisor.canonicalizar(repo), detalhe=descricao,
                      **_campos_de_autoridade(autoridade),
                      sandbox=True, rede=False,
                      classificacao=p.classificacao,
                      morto_por_timeout=p.morto_por_timeout)
        # PONTO DE COMMIT — a ÚLTIMA coisa que acontece, e por medição.
        #
        # A promoção estava antes da auditoria, e a bateria pegou: com o
        # `_auditar` levantando, o blob do segredo JÁ tinha ido para o store
        # permanente, o índice voltava atrás, e sobrava exatamente o objeto
        # inalcançável que A0.3 existe para eliminar. Qualquer passo que possa
        # falhar precisa vir ANTES daqui; depois desta linha a operação está
        # aceita e nada mais pode recusá-la.
        _promover_quarentena(Path(quarentena.diretorio),
                             Path(quarentena.alternativos),
                             raiz_do_store=autoridade.common)
        return CapabilityResult.sucesso(descricao, efeito_aplicado=True)

    # ---------------------------------------------------------------- argvs

    def _base(self, repo: Path) -> list[str]:
        # A working tree é PINADA, mas por `GIT_WORK_TREE` e não por `-c` — ver
        # `ambiente()`. MEDIDO: `-c core.worktree=<repo>` NÃO vence a chave do
        # `.git/config` (o Git segue reportando `/private/etc`), então a
        # neutralização por linha de comando, que funciona para todas as outras
        # chaves desta lista, aqui seria um no-op silencioso.
        return [self._git, "-C", str(repo), "--no-pager",
                *_NEUTRALIZAR, *_NEUTRALIZAR_TREE]

    def _add(self, pedido, repo: Path, prazo: float,
             autoridade) -> tuple[list[str], str]:
        brutos = pedido.arg("caminhos")
        if not isinstance(brutos, (list, tuple)):
            raise ErroInvalido(
                "'caminhos' deve ser lista de caminhos relativos — não existe "
                "forma de pedir 'tudo': o operador aprova uma lista")
        if not brutos:
            raise ErroInvalido("'caminhos' vazio")
        if len(brutos) > MAX_CAMINHOS:
            raise ErroLimite(f"acima de {MAX_CAMINHOS} caminhos por operação")
        caminhos = [caminho_relativo(c, i) for i, c in enumerate(brutos)]
        self._recusar_diretorio(repo, caminhos)

        # A5.7 — separa os caminhos que o repositório PEDE filtro para. Eles
        # saem do `git add` e passam pelo caminho governado; o resto segue
        # exatamente como antes. Sem registry, não há separação nenhuma.
        governados: dict[str, str] = {}
        if self._registro is not None:
            governados = self._pedidos_de_filtro(repo, caminhos, prazo,
                                                 autoridade)

        restantes = [c for c in caminhos if c not in governados]
        argv = (self._base(repo) + ["add", "--no-all", "--"] + restantes
                if restantes else [])
        if governados:
            return argv, (f"add {len(caminhos)} caminho(s) "
                          f"({len(governados)} por filtro governado)"), governados, caminhos
        return argv, f"add {len(caminhos)} caminho(s)", governados, caminhos

    def _conferir_head(self, repo: Path, prazo: float, autoridade) -> None:
        """`HEAD` tem de apontar para um BRANCH, e o repositório escreve `HEAD`.

        MEDIDO, dois desfechos, os dois com `ok=True valor='commit'`:

            HEAD -> refs/tags/v1.0        o commit MUTA a tag (8b2ceeff → …)
            HEAD -> refs/replace/<sha>    o commit INSTALA substituição de objeto

        `git commit` grava onde `HEAD` mandar, e `.git/HEAD` é do repositório. O
        segundo é o mais grave: uma vez instalado o replace, toda leitura
        posterior do NOMOS passa a servir outro objeto — e é o commit governado
        que planta a arma.

        A regra é a que o fluxo legítimo já obedece sem saber: um commit
        atualiza um branch sob `refs/heads/`. Ref simbólica para tag, para
        `refs/replace`, ou `HEAD` destacado (raw sha, escolhido pelo repo via
        symlink) não são commit — são gravar num lugar que muda a semântica do
        repositório.

        `GIT_NO_REPLACE_OBJECTS=1` (em `ambiente_minimo`) fecha a mesma porta
        pelo outro lado; este guard recusa ANTES de executar, com a mensagem do
        porquê. MEDIDO ao tentar pôr as duas defesas juntas:
        `--no-replace-objects` é opção de NÍVEL DO GIT, não do subcomando, e
        `git commit --no-replace-objects` sai com rc=129 `unknown option` —
        quebrando TODO commit legítimo. A variável de ambiente cobre as sete
        capacidades sem essa armadilha de posição.
        """
        argv = self._base(repo) + ["symbolic-ref", "--quiet", "HEAD"]
        p = supervisor.executar(
            argv, cwd=repo, env=self.ambiente(), prazo=prazo,
            confinamento=confinamento_de_leitura(repo, autoridade),
            arvore_de_trabalho=str(repo))
        if p.returncode == 1:
            # rc=1 = HEAD DESTACADO (não é symref). Um commit aqui não avança
            # branch nenhum; e o vetor do symlink de HEAD chega exatamente assim.
            raise ErroSeguranca(
                "HEAD está destacado (não aponta para um branch). Um commit "
                "governado atualiza um branch sob refs/heads/; HEAD destacado "
                "grava um commit que nenhum branch alcança — e é a forma que o "
                "symlink de HEAD escolhido pelo repositório assume")
        # Morte por SINAL não é erro de sintaxe. MEDIDO (`.6.10`): `rc=-9`
        # (SIGKILL, inclusive o do prazo) caía no mesmo ramo de um HEAD
        # malformado e subia como `ErroInvalido('symbolic-ref HEAD falhou')`.
        # Fecha igual — não há efeito no disco — mas a CLASSIFICAÇÃO mente, e é
        # dela que a auditoria e o operador vivem. Os demais caminhos do módulo
        # já consultam `morto_por_timeout` e mapeiam para `ErroLimite`; este
        # ficara de fora.
        if p.morto_por_timeout or p.returncode < 0:
            raise ErroLimite(
                f"symbolic-ref HEAD foi encerrado por sinal (rc={p.returncode})"
                f"{' após o prazo' if p.morto_por_timeout else ''} — a árvore "
                "de processos foi morta, não houve resposta a interpretar")
        if p.returncode != 0:
            erro = p.stderr.decode("utf-8", "replace")[:400]
            raise ErroInvalido(f"symbolic-ref HEAD falhou (rc={p.returncode}): {erro}")
        destino = p.stdout.decode("utf-8", "replace").strip()
        if not destino.startswith("refs/heads/"):
            raise ErroSeguranca(
                f"HEAD aponta para {destino!r}, fora de refs/heads/. O "
                "repositório escreve `.git/HEAD`, e um commit segue esse "
                "ponteiro: para refs/tags/ ele MUTA uma tag, para refs/replace/ "
                "ele INSTALA substituição de objeto que falsifica toda leitura "
                "posterior. Commit governado só avança um branch")

    def _commit(self, pedido, repo: Path, prazo: float,
                autoridade) -> tuple[list[str], str]:
        msg = mensagem_valida(pedido.arg("mensagem"))
        for proibido in ("autor", "author", "data", "date", "amend"):
            if pedido.arg(proibido, None) is not None:
                raise ErroInvalido(
                    f"'{proibido}' não é aceito: autoria vem do runtime e "
                    "`amend` reescreveria histórico já auditado")
        self._conferir_head(repo, prazo, autoridade)
        argv = self._base(repo) + [
            "commit", "--no-verify", "--no-gpg-sign",
            "--cleanup=verbatim", "-m", msg]
        return argv, "commit"
