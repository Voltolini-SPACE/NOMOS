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

import re
from dataclasses import dataclass
from pathlib import Path

from nomos.adapters import supervisor
from nomos.adapters.caminho import resolver
from nomos.adapters.contrato import (
    Adapter, CapabilityContext, CapabilityRequest, CapabilityResult,
    ErroInvalido, ErroLimite,
)
from nomos.adapters.estrito import texto_estrito
from nomos.adapters.git import _NEUTRALIZAR, ambiente_minimo, confinamento_de_repo

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
        p = supervisor.executar(argv, cwd=repo, env=self.ambiente(),
                                prazo=prazo,
                                confinamento=confinamento_de_repo(repo))
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
