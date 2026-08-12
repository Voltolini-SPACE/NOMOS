"""NOMOS adapters.git_write — C2a: escrita de REFERÊNCIA, e só isso.

O C2 original previa `add`, `commit`, `tag` e `push` juntos. A medição do
`git add` desfez esse plano: com `filter.hostil.clean` definido pelo próprio
repositório, `git add` executou o programa do repo com `RC=0`, sem stderr e
sem nenhum sinal externo. O filtro É o mecanismo pelo qual o Git transforma
conteúdo do working tree em objeto — desligá-lo mudaria o que fica gravado,
não protegeria.

Sobrou a divisão por fronteira de confiança, não por conveniência:

    C2a (aqui)  git-tag      referência sobre objeto JÁ commitado
    C2b         git-push     atravessa fronteira de rede
    C2c         git-add      toca working tree → executa código do repo
                git-commit   depende do índice que o `add` preparou

`git-commit` está em C2c mesmo parecendo operação de objeto: uma cadeia é tão
confiável quanto o elo que executa código do repositório.

## Por que lightweight tag

Tag anotada exige mensagem, e mensagem convida editor (`core.editor`,
`GIT_EDITOR`, `commit.template`) e assinatura (`tag.gpgSign`, `gpg.program`) —
três caminhos de execução externa para uma operação cujo efeito é escrever
vinte bytes num arquivo de ref. A primeira versão não tem mensagem: não há o
que editar nem o que assinar.

Tag anotada e assinada, se forem necessárias, ganham capacidade própria com o
mesmo escrutínio — não um parâmetro opcional aqui.
"""
from __future__ import annotations

import re

from nomos.adapters import supervisor
from nomos.adapters.caminho import resolver
from nomos.adapters.contrato import (
    Adapter, CapabilityContext, CapabilityRequest, CapabilityResult,
    ErroInvalido, ErroLimite, ErroNaoEncontrado,
)
from nomos.adapters.estrito import texto_estrito
from nomos.adapters.git import (
    _NEUTRALIZAR, ambiente_minimo, autoridade_de, confinamento_de_repo,
    conferir_alternates, conferir_git_dir,
    ref_valida,
)

CAPACIDADES = ("git-tag",)

TIMEOUT_S = 20.0

# Gramática de NOME de tag. Mais restritiva que a de ref: nome de tag é
# escolhido por quem cria, então não há motivo para aceitar as formas
# esotéricas que o Git tolera em ref existente.
_TAG_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_TAG_PROIBIDO = re.compile(
    r"(^-)|(\.\.)|(@\{)|(\s)|(/)|([\x00-\x1f;&|`$(){}\[\]<>*?!\\'\"~^:])")

# Chaves do REPOSITÓRIO que executam programa no caminho de `tag`. Diferente
# do C1, aqui a neutralização NÃO é redundante: `tag.gpgSign=true` faria o Git
# chamar `gpg.program`, e `core.hooksPath` traz hooks de referência.
_NEUTRALIZAR_TAG = [
    "-c", "tag.gpgSign=false",
    "-c", "tag.forceSignAnnotated=false",
    "-c", "gpg.program=true",
    "-c", "core.editor=true",
    "-c", "commit.template=",
]


def tag_valida(bruta: str) -> str:
    """Nome de tag seguro, ou `ErroInvalido`.

    `-` no início é recusado antes de tudo: `git tag -d x` apaga, `git tag -f`
    sobrescreve. Uma "tag" que começa com `-` é opção, e opções de tag mutam
    ou destroem referência.
    """
    texto = texto_estrito(bruta, "tag", obrigatorio=True, maximo=100)
    if _TAG_PROIBIDO.search(texto):
        raise ErroInvalido(
            f"nome de tag inválido: {texto!r}. Não pode começar com '-' (o Git "
            "leria como OPÇÃO — `-d` apaga, `-f` sobrescreve), nem conter "
            "espaço, barra, controle ou metacaractere")
    if not _TAG_OK.match(texto):
        raise ErroInvalido(f"nome de tag fora da gramática: {texto!r}")
    return texto


class GitTagAdapter(Adapter):
    """Cria tag LEVE sobre um objeto já existente. Não toca working tree."""

    capacidades = CAPACIDADES

    def __init__(self, binario: str | None = None):
        self._git = binario or "/usr/bin/git"

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
        # BIND AUTHORITY — ver `AutoridadeDeRepo`: valida uma vez e leva
        # adiante, para o efeito não reler `.git` do disco (TOCTOU medido).
        _gd, _comum = conferir_git_dir(repo, ctx.raizes)
        autoridade = autoridade_de(repo, _gd, _comum)
        conferir_alternates(repo, ctx.raizes, autoridade)

        nome = tag_valida(pedido.arg("tag"))
        # O parâmetro chama-se `objeto`, não `target`. A defesa do P3 trata
        # `alvo` e `target` como ALIASES da mesma autoridade e recusa os dois
        # juntos — e `git-tag` precisa de ambos: `alvo` é o repositório,
        # `target` seria o commit. Quem cede é o nome do parâmetro novo, nunca
        # a checagem de ambiguidade: enfraquecer o alias para caber uma
        # capacidade seria trocar uma defesa provada por conveniência de
        # nomenclatura. `objeto` também é mais honesto — é o objeto git que
        # a tag aponta.
        #
        # OBRIGATÓRIO. Ausência NÃO vira HEAD: um default que muda o objeto
        # marcado transforma "marque este commit" em "marque o que estiver por
        # aí", e o operador aprovou a primeira coisa.
        alvo_ref = ref_valida(pedido.arg("objeto"), "objeto")

        argv = [self._git, "-C", str(repo), "--no-pager",
                *_NEUTRALIZAR, *_NEUTRALIZAR_TAG,
                "tag", nome, alvo_ref]
        prazo = min(TIMEOUT_S, ctx.restante() or TIMEOUT_S)
        p = supervisor.executar(argv, cwd=repo, env=ambiente_minimo(),
                                prazo=prazo,
                                confinamento=confinamento_de_repo(repo, autoridade=autoridade))
        if p.morto_por_timeout:
            raise ErroLimite(f"git tag excedeu {prazo:.1f}s")
        if p.returncode != 0:
            erro = p.stderr.decode("utf-8", "replace")[:400]
            if "not a valid object name" in erro or "Failed to resolve" in erro:
                raise ErroNaoEncontrado(f"target não existe: {alvo_ref}")
            raise ErroInvalido(f"git tag falhou (rc={p.returncode}): {erro}")
        supervisor.conferir_saida(p.stderr, "git tag")
        self._auditar(ctx, "git.tag", alvo=supervisor.canonicalizar(repo),
                      git_dir=autoridade.git_dir, common_dir=autoridade.common,
                      tag=nome, target=alvo_ref, sandbox=True, rede=False,
                      classificacao=p.classificacao,
                      morto_por_timeout=p.morto_por_timeout)
        return CapabilityResult.sucesso(f"{nome} -> {alvo_ref}",
                                        efeito_aplicado=True)
