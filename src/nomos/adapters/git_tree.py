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
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

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
    diretorio_git,
)

CAPACIDADES = ("git-add", "git-commit")

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
                 identidade: Identidade | None = None):
        self._git = binario or "/usr/bin/git"
        self._id = identidade or Identidade()

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

        if pedido.capacidade == "git-add":
            argv, descricao = self._add(pedido, repo)
        elif pedido.capacidade == "git-commit":
            argv, descricao = self._commit(pedido, repo)
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
                                quarentena)
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

    def _confirmar(self, pedido, ctx, repo: Path, argv: list[str],
                   descricao: str, prazo: float,
                   quarentena: supervisor.Quarentena) -> CapabilityResult:
        """Executa e valida. Qualquer saída por exceção desfaz o índice.

        A promoção dos objetos acontece DEPOIS de todas as verificações: um
        objeto só chega ao store permanente quando a operação inteira foi
        aceita. É isso que impede o segredo de um filtro quebrado de existir
        fora da quarentena, em vez de apagá-lo depois de gravado.
        """
        p = supervisor.executar(argv, cwd=repo, env=self.ambiente(),
                                prazo=prazo,
                                confinamento=confinamento_de_repo(repo),
                                quarentena=quarentena)
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
        argv = self._base(repo) + ["add", "--no-all", "--"] + caminhos
        return argv, f"add {len(caminhos)} caminho(s)"

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
