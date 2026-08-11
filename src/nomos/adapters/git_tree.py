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
import fnmatch
import os
import re
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
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
    confinamento_de_repo,
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
_ATRIBUTO_FILTRO = re.compile(r"^\s*(?P<padrao>\S+)\s+(?P<resto>.*)$")
_FILTRO_NO_ATRIBUTO = re.compile(r"(?:^|\s)filter=(?P<id>[^\s]+)")
MAX_ATRIBUTOS = 500
MAX_CONTEUDO = 64 * 1024 * 1024

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
]


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
    alvo = repo / caminho
    try:
        st = os.lstat(alvo)
    except OSError as e:
        raise ErroInvalido(f"não consegui inspecionar {caminho}: {e}") from None
    if stat.S_ISLNK(st.st_mode):
        raise ErroSeguranca(
            f"{caminho} é um symlink, e filtro governado não segue link: o "
            "conteúdo lido seria o do DESTINO, escolhido pelo repositório, e a "
            "leitura acontece no processo do supervisor — fora do sandbox do "
            "filtro. Um link para segredo do host viraria conteúdo indexado")
    if not stat.S_ISREG(st.st_mode):
        raise ErroSeguranca(
            f"{caminho} não é arquivo regular (modo {st.st_mode:o}) — FIFO e "
            "device penduram a leitura do supervisor sem prazo nenhum")
    if st.st_size > MAX_CONTEUDO:
        raise ErroLimite(
            f"{caminho} tem {st.st_size} bytes (limite {MAX_CONTEUDO})")

    # `O_NOFOLLOW` fecha a corrida entre o `lstat` e o `open`: sem ele, trocar o
    # arquivo por link entre as duas chamadas devolveria o destino do link.
    try:
        fd = os.open(alvo, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as e:
        raise ErroInvalido(f"não consegui ler {caminho}: {e}") from None
    try:
        # Reconfere pelo DESCRITOR já aberto: é o mesmo objeto que vai ser lido,
        # e não um caminho que pode ter mudado de significado no meio.
        st2 = os.fstat(fd)
        if not stat.S_ISREG(st2.st_mode):
            raise ErroSeguranca(f"{caminho} deixou de ser arquivo regular")
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


def _instantaneo_do_indice(repo: Path) -> tuple[Path, bytes | None, int | None]:
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
    git_dir, _ = diretorio_git(repo)
    alvo = Path(git_dir) / "index"
    if not alvo.exists():
        # Repositório recém-criado ainda não tem índice. "Restaurar" aqui
        # significa fazer o arquivo deixar de existir de novo.
        return alvo, None, None
    return alvo, alvo.read_bytes(), alvo.stat().st_mode


def _restaurar_indice(inst: tuple[Path, bytes | None, int | None]) -> None:
    """Devolve o índice ao estado do instantâneo, atomicamente."""
    alvo, dados, modo = inst
    if dados is None:
        alvo.unlink(missing_ok=True)
        return
    # Escrever direto em `index` deixaria uma janela com arquivo truncado, que
    # o Git leria como índice corrompido. `os.replace` no MESMO diretório é
    # rename atômico: ou o índice antigo, ou o restaurado, nunca um meio-termo.
    tmp = alvo.with_name(f".index.nomos-rollback-{os.getpid()}")
    try:
        tmp.write_bytes(dados)
        if modo is not None:
            os.chmod(tmp, modo)
        os.replace(tmp, alvo)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()


def _abrir_quarentena(repo: Path) -> tuple[supervisor.Quarentena, Path]:
    """Object store descartável desta operação, dentro do próprio git dir.

    Fica no git dir porque essa área JÁ é a autoridade de escrita concedida
    (`confinamento_de_repo`), então a quarentena não amplia nada. Um diretório
    em `/tmp` exigiria abrir mais uma raiz de escrita no sandbox — autoridade
    nova para resolver um problema de contenção seria o caminho errado.
    """
    git_dir, comum = diretorio_git(repo)
    reais = Path(comum) / "objects"
    raiz = Path(tempfile.mkdtemp(prefix="nomos-quarentena-", dir=git_dir))
    return supervisor.Quarentena(diretorio=str(raiz),
                                 alternativos=str(reais)), reais


def _promover_quarentena(raiz: Path, reais: Path) -> int:
    """Move os objetos aceitos para o store permanente. Devolve quantos."""
    movidos = 0
    for origem in sorted(raiz.rglob("*")):
        if not origem.is_file():
            continue
        destino = reais / origem.relative_to(raiz)
        if destino.exists():
            # Objeto endereçado por conteúdo: mesmo SHA, mesmos bytes. Já
            # existir é deduplicação, não conflito.
            continue
        destino.parent.mkdir(parents=True, exist_ok=True)
        os.replace(origem, destino)
        movidos += 1
    return movidos


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
        if not (repo / ".git").exists():
            raise ErroInvalido(f"não é repositório git: {repo}")
        # A2-REPO: o `.git` do repositorio pode ser um ARQUIVO apontando o git
        # dir para fora das raizes aprovadas, e o git dir vira RAIZ DE ESCRITA
        # do sandbox. Conferir aqui, junto do `resolver`, porque e aqui que as
        # raizes existem — e antes de qualquer I/O que use o caminho.
        conferir_git_dir(repo, ctx.raizes)

        # `governados` viaja como ARGUMENTO até `_confirmar`, e não guardado no
        # adapter. Estado de operação em `self` faria duas operações
        # simultâneas no mesmo adapter trocarem de plano no meio — a `add` de um
        # repositório aplicando o filtro escolhido para outro.
        if pedido.capacidade == "git-add":
            argv, descricao, governados = self._add(pedido, repo)
        elif pedido.capacidade == "git-commit":
            argv, descricao = self._commit(pedido, repo)
            governados = {}
        else:
            raise ErroInvalido(f"operação desconhecida: {pedido.capacidade}")

        prazo = min(TIMEOUT_S, ctx.restante() or TIMEOUT_S)
        # A partir daqui a operação é TRANSACIONAL: ou confirma, ou o índice
        # volta ao byte anterior. Detectar a falha e deixar o índice sujo era
        # detecção sem contenção — o `git add` já tinha estagiado o conteúdo
        # cru, e um `git commit` posterior persistiria o segredo mesmo com o
        # `add` tendo sido RECUSADO. O instantâneo é tirado ANTES do exec.
        instantaneo = _instantaneo_do_indice(repo)
        quarentena, reais = _abrir_quarentena(repo)
        raiz_q = Path(quarentena.diretorio)
        try:
            r = self._confirmar(pedido, ctx, repo, argv, descricao, prazo,
                                quarentena, governados)
        except BaseException:
            # BaseException, não Exception: KeyboardInterrupt e SystemExit
            # também não podem deixar segredo estagiado nem objeto no store.
            _restaurar_indice(instantaneo)
            raise
        finally:
            # A quarentena some nos DOIS caminhos. No sucesso ela já foi
            # esvaziada pela promoção (dentro de `_confirmar`, depois de TODAS
            # as verificações); na falha ela some cheia, levando junto o objeto
            # que o filtro gravou. Nunca `git gc`: isto apaga um diretório que
            # só esta execução escreveu, e nada mais.
            shutil.rmtree(raiz_q, ignore_errors=True)
        return r

    # ------------------------------------------------- A5.7 filtro governado

    def _pedidos_de_filtro(self, repo: Path,
                           caminhos: list[str]) -> dict[str, str]:
        """Lê o `.gitattributes` e devolve `{caminho: filter_id PEDIDO}`.

        É a única coisa que o repositório contribui, e é tratada como entrada
        hostil: o id passa por `conferir_id` aqui, ANTES de virar consulta ao
        registry, para que um id que pareça caminho (`../`, `/etc/x`) nem chegue
        perto de algo que resolva caminho.

        Sem `.gitattributes`, sem pedido — e sem pedido, o caminho é o normal.
        """
        from nomos.adapters import filtro_governado as fg

        arquivo = repo / ".gitattributes"
        if not arquivo.is_file():
            return {}
        try:
            linhas = arquivo.read_text("utf-8", "replace").splitlines()
        except OSError:
            return {}
        if len(linhas) > MAX_ATRIBUTOS:
            raise ErroLimite(
                f".gitattributes com {len(linhas)} linhas (limite "
                f"{MAX_ATRIBUTOS}) — recuso em vez de varrer entrada ilimitada "
                "vinda do repositório")
        regras: list[tuple[str, str]] = []
        for linha in linhas:
            if not linha.strip() or linha.lstrip().startswith("#"):
                continue
            m = _ATRIBUTO_FILTRO.match(linha)
            if not m:
                continue
            f = _FILTRO_NO_ATRIBUTO.search(m.group("resto"))
            if f:
                regras.append((m.group("padrao"), f.group("id")))


        pedidos: dict[str, str] = {}
        for caminho in caminhos:
            for padrao, bruto in regras:          # última regra vence, como no Git
                alvo = caminho if "/" in padrao else os.path.basename(caminho)
                if fnmatch.fnmatch(alvo, padrao):
                    pedidos[caminho] = fg.conferir_id(bruto)
        return pedidos

    def _aplicar_filtro_governado(self, repo: Path, caminho: str,
                                  filter_id: str, prazo: float,
                                  quarentena: supervisor.Quarentena) -> str:
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
            confinamento=confinamento_de_repo(repo), quarentena=quarentena,
            entrada=p.stdout, arvore_de_trabalho=str(repo))
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
                  quarentena: supervisor.Quarentena) -> None:
        """Põe o blob transformado no índice, sem passar pela working tree."""
        modo = "100755" if os.access(repo / caminho, os.X_OK) else "100644"
        u = supervisor.executar(
            self._base(repo) + ["update-index", "--add", "--cacheinfo",
                                f"{modo},{sha},{caminho}"],
            cwd=repo, env=self.ambiente(), prazo=prazo,
            confinamento=confinamento_de_repo(repo), quarentena=quarentena,
            arvore_de_trabalho=str(repo))
        if u.returncode != 0:
            erro = u.stderr.decode("utf-8", "replace")[:400]
            raise ErroInvalido(f"update-index falhou em {caminho}: {erro}")
        supervisor.conferir_saida(u.stderr, "git-add")

    def _confirmar(self, pedido, ctx, repo: Path, argv: list[str],
                   descricao: str, prazo: float,
                   quarentena: supervisor.Quarentena,
                   governados: dict[str, str]) -> CapabilityResult:
        """Executa e valida. Qualquer saída por exceção desfaz o índice.

        A promoção dos objetos acontece DEPOIS de todas as verificações: um
        objeto só chega ao store permanente quando a operação inteira foi
        aceita. É isso que impede o segredo de um filtro quebrado de existir
        fora da quarentena, em vez de apagá-lo depois de gravado.
        """
        for caminho, filter_id in governados.items():
            sha = self._aplicar_filtro_governado(repo, caminho, filter_id,
                                                 prazo, quarentena)
            self._estagiar(repo, caminho, sha, prazo, quarentena)
        if governados and not argv:
            # TODOS os caminhos eram governados: não sobrou `git add` para
            # rodar, e inventar um rodaria o Git sobre a working tree CRUA —
            # desfazendo, no último passo, a transformação que acabou de ser
            # aplicada.
            self._auditar(ctx, "git.add",
                          alvo=supervisor.canonicalizar(repo),
                          detalhe=descricao, sandbox=True, rede=False,
                          classificacao="EXIT_OK", morto_por_timeout=False)
            _promover_quarentena(Path(quarentena.diretorio),
                                 Path(quarentena.alternativos))
            return CapabilityResult.sucesso(descricao, efeito_aplicado=True)

        p = supervisor.executar(argv, cwd=repo, env=self.ambiente(),
                                prazo=prazo,
                                confinamento=confinamento_de_repo(repo),
                                quarentena=quarentena,
                                arvore_de_trabalho=str(repo))
        if p.morto_por_timeout:
            # O filtro do repositório pendura o processo — medido, não suposto.
            # A árvore inteira já morreu; o que resta é recusar.
            raise ErroLimite(
                f"{pedido.capacidade} excedeu {prazo:.1f}s e a árvore de "
                "processos foi encerrada (provável filtro do repositório)")
        if p.returncode != 0:
            erro = p.stderr.decode("utf-8", "replace")[:400]
            raise ErroInvalido(
                f"{pedido.capacidade} falhou (rc={p.returncode}): {erro}")
        # `git add` é a ÚNICA capacidade que roda programa do repositório (o
        # filtro). É também onde o rc=0 mente com mais consequência: filtro
        # quebrado indexa o conteúdo cru. Aqui a mentira para.
        supervisor.conferir_saida(p.stderr, pedido.capacidade)
        self._auditar(ctx, f"git.{pedido.capacidade[4:]}",
                      alvo=supervisor.canonicalizar(repo), detalhe=descricao,
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
                             Path(quarentena.alternativos))
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

    def _add(self, pedido, repo: Path) -> tuple[list[str], str]:
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

        # A5.7 — separa os caminhos que o repositório PEDE filtro para. Eles
        # saem do `git add` e passam pelo caminho governado; o resto segue
        # exatamente como antes. Sem registry, não há separação nenhuma.
        governados: dict[str, str] = {}
        if self._registro is not None:
            governados = self._pedidos_de_filtro(repo, caminhos)

        restantes = [c for c in caminhos if c not in governados]
        argv = (self._base(repo) + ["add", "--no-all", "--"] + restantes
                if restantes else [])
        if governados:
            return argv, (f"add {len(caminhos)} caminho(s) "
                          f"({len(governados)} por filtro governado)"), governados
        return argv, f"add {len(caminhos)} caminho(s)", governados

    def _commit(self, pedido, repo: Path) -> tuple[list[str], str]:
        msg = mensagem_valida(pedido.arg("mensagem"))
        for proibido in ("autor", "author", "data", "date", "amend"):
            if pedido.arg(proibido, None) is not None:
                raise ErroInvalido(
                    f"'{proibido}' não é aceito: autoria vem do runtime e "
                    "`amend` reescreveria histórico já auditado")
        argv = self._base(repo) + [
            "commit", "--no-verify", "--no-gpg-sign",
            "--cleanup=verbatim", "-m", msg]
        return argv, "commit"
