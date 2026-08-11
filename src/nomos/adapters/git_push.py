"""NOMOS adapters.git_push — C2b: escrita REMOTA, com destino comprometido.

`push` não é "mais um comando git". É a única operação desta série que
atravessa fronteira de confiança: publica em servidor de terceiro, pode
disparar CI, webhooks e deploy, e não tem desfazer sem cooperação do remoto.

## O TOCTOU central

    aprovar remote=origin
      → `.git/config` muda
      → origin passa a apontar para destino hostil
      → push

Confiar no NOME do remote é confiar em `.git/config`, que é dado vindo de fora.
A política é dona do destino: `remote_id` referencia um destino GOVERNADO
(scheme, host, porta, caminho, branch de destino, credencial), e o `.git/config`
vira apenas uma fonte a conferir — nunca a fonte de autoridade.

## Por que passar a URL na linha de comando NÃO basta

Mesmo ignorando `remote.<nome>.url` e `remote.<nome>.pushurl`, o Git aplica
`url.<base>.insteadOf` e `url.<base>.pushInsteadOf` a QUALQUER URL — inclusive
à que vem no argv. Um repositório com

    [url "<destino-do-atacante>"]
        insteadOf = <destino-autorizado>

reescreve o destino autorizado para o do atacante, e o `git push` obedece.

Por isso a verificação pergunta ao PRÓPRIO Git qual URL ele usaria
(`ls-remote --get-url`) e compara com a autorizada. Se diferirem, é recusa:
o repositório tentou redirecionar a publicação.

## Sem refspec do plano

O adapter monta `refs/heads/<origem>:refs/heads/<destino>` a partir de nomes
validados. Refspec livre traz `+` (force), `HEAD:qualquer`, `refs/*:refs/*` —
cada um uma autoridade diferente da que foi aprovada.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from nomos.adapters.caminho import resolver
from nomos.adapters.contrato import (
    Adapter, CapabilityContext, CapabilityRequest, CapabilityResult,
    ErroInvalido, ErroLimite,
)
from nomos.adapters.estrito import texto_estrito
from nomos.adapters import supervisor
from nomos.adapters.git import (
    _NEUTRALIZAR, ambiente_minimo, confinamento_de_repo, conferir_git_dir,
)

CAPACIDADES = ("git-push",)
TIMEOUT_S = 60.0

# Nome de branch: gramática própria, mais estrita que ref genérica. Branch de
# push é escolhida por quem publica, então não há motivo para aceitar as
# formas esotéricas que o Git tolera.
_BRANCH_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$")
_BRANCH_PROIBIDO = re.compile(
    r"(^-)|(^\+)|(\.\.)|(@\{)|(\s)|(//)|([\x00-\x1f;&|`$(){}\[\]<>*?!\\'\":^~])")

# Config do repositório que redireciona destino ou executa programa no caminho
# do push. `url.*.insteadOf` NÃO pode ser neutralizado por `-c` (a chave é
# variável), por isso a defesa contra ele é a COMPARAÇÃO da URL efetiva.
_NEUTRALIZAR_PUSH = [
    "-c", "credential.helper=",
    "-c", "core.sshCommand=false",
    "-c", "core.askPass=",
    "-c", "push.default=nothing",
    "-c", "push.followTags=false",
    "-c", "remote.pushDefault=",
    "-c", "protocol.ext.allow=never",
    "-c", "protocol.file.allow=always",   # bare repo local, usado nos testes
]


class ErroRemoto(ErroInvalido):
    """Destino remoto não autorizado, redirecionado ou divergente."""


@dataclass(frozen=True)
class DestinoGovernado:
    """O destino que a POLÍTICA autoriza. Não vem do repositório nem do plano."""
    remote_id: str
    url: str
    branch_destino: str
    credential_id: str = ""

    def partes(self) -> dict:
        p = urlsplit(self.url)
        return {"scheme": p.scheme or "file", "host": p.hostname or "",
                "port": str(p.port or ""), "repository": p.path}

    def canonico(self) -> dict:
        return {"remote_id": self.remote_id, "resolved_url": self.url,
                "destination_branch": self.branch_destino,
                "credential_id": self.credential_id, **self.partes()}


def branch_valida(bruta, nome: str) -> str:
    """Nome de branch seguro. `-` e `+` recusados antes de tudo.

    `+` é o prefixo de force no refspec: `+main:main` sobrescreve histórico no
    remoto. Uma "branch" que começa com `+` não é branch, é uma força.
    """
    texto = texto_estrito(bruta, nome, obrigatorio=True, maximo=100)
    if _BRANCH_PROIBIDO.search(texto):
        raise ErroInvalido(
            f"'{nome}' inválido: {texto!r}. Não pode começar com '-' (opção) "
            "nem '+' (force no refspec), nem conter espaço, controle ou "
            "metacaractere")
    if not _BRANCH_OK.match(texto):
        raise ErroInvalido(f"'{nome}' fora da gramática: {texto!r}")
    return texto


class GitPushAdapter(Adapter):
    """Publica UMA branch num destino governado, com o destino reconferido."""

    capacidades = CAPACIDADES

    def __init__(self, destinos: dict[str, DestinoGovernado] | None = None,
                 binario: str | None = None):
        # Os destinos vêm da POLÍTICA/runtime, nunca do plano nem do repo.
        self._destinos = dict(destinos or {})
        self._git = binario or "/usr/bin/git"

    # ------------------------------------------------------------ resolução

    def destino_de(self, remote_id: str) -> DestinoGovernado:
        d = self._destinos.get(remote_id)
        if d is None:
            raise ErroRemoto(
                f"remote_id desconhecido: {remote_id!r} — destinos de push são "
                "declarados na política, não no repositório nem no plano")
        return d

    def url_efetiva(self, repo, url_autorizada: str) -> str:
        """A URL que o Git REALMENTE usaria para esta, após reescritas.

        `url.<base>.insteadOf` do repositório reescreve qualquer URL, inclusive
        a que vem no argv. Perguntar ao próprio Git é a única forma de saber o
        destino efetivo sem reimplementar a regra de reescrita.
        """
        argv = [self._git, "-C", str(repo), "--no-pager",
                *_NEUTRALIZAR, *_NEUTRALIZAR_PUSH,
                "ls-remote", "--get-url", url_autorizada]
        p = supervisor.executar(argv, cwd=repo, env=ambiente_minimo(),
                                prazo=15.0,
                                confinamento=confinamento_de_repo(repo))
        if p.returncode != 0:
            raise ErroRemoto("não consegui resolver a URL efetiva do destino")
        return p.stdout.decode("utf-8", "replace").strip()

    def regras_de_reescrita(self, repo) -> list[str]:
        """Qualquer `url.*.insteadOf` / `pushInsteadOf` declarada no repo.

        `ls-remote --get-url` mostra a reescrita de FETCH; `pushInsteadOf`
        atua só no push e passaria despercebido — foi o que o teste do bare
        hostil pegou, com a publicação chegando ao remote errado. Em vez de
        tentar prever a resolução de push, recuso a EXISTÊNCIA de regra de
        reescrita: um repositório que quer redirecionar publicação não tem
        motivo legítimo para fazê-lo pelas costas do destino governado.
        """
        argv = [self._git, "-C", str(repo), "--no-pager", *_NEUTRALIZAR,
                "config", "--get-regexp",
                r"^url\..*\.(insteadof|pushinsteadof)$"]
        p = supervisor.executar(argv, cwd=repo, env=ambiente_minimo(),
                                prazo=15.0,
                                confinamento=confinamento_de_repo(repo))
        if p.returncode not in (0, 1):     # 1 = nenhuma chave, normal
            raise ErroRemoto("não consegui inspecionar regras de reescrita")
        return [linha for linha in p.stdout.decode("utf-8", "replace").splitlines()
                if linha.strip()]

    def conferir_destino(self, repo, destino: DestinoGovernado) -> str:
        """Recusa se o repositório redirecionar a URL autorizada."""
        regras = self.regras_de_reescrita(repo)
        if regras:
            raise ErroRemoto(
                "o repositório declara regra de REESCRITA de URL "
                f"({len(regras)}: {regras[0][:80]}). Publicação com destino "
                "governado não convive com reescrita — o destino aprovado "
                "deixaria de ser o destino efetivo")
        efetiva = self.url_efetiva(repo, destino.url)
        if efetiva != destino.url:
            raise ErroRemoto(
                f"o repositório REDIRECIONA o destino autorizado: "
                f"{destino.url!r} viraria {efetiva!r}. Provável "
                "`url.*.insteadOf` no .git/config — a publicação iria para "
                "outro servidor")
        return efetiva

    # --------------------------------------------------------- confinamento

    @staticmethod
    def _local(destino: DestinoGovernado) -> str:
        """Caminho local do destino, ou `""` se ele estiver na rede."""
        p = urlsplit(destino.url)
        if p.scheme in ("", "file") and not p.hostname:
            return p.path or destino.url
        return ""

    def confinamento(self, repo, destino: DestinoGovernado):
        """A autoridade de `push` é derivada do DESTINO GOVERNADO, nunca do plano.

        Rede não é concedida por padrão nem sequer aqui: um destino `file://`
        publica sem tocar a rede, e conceder `allow network*` a ele seria
        entregar egresso que a operação não usa. Um destino remoto recebe rede
        porque o egresso É o efeito autorizado — já filtrado antes por
        `A2_NET_EGRESS` e por `localidade.json`.

        O caminho local do destino entra na escrita porque publicar num bare
        repo é escrevê-lo. Ele vem da POLÍTICA, então isso não amplia o que o
        plano alcança: quem escolhe o destino é quem escreveu a política.
        """
        local = self._local(destino)
        raizes = [supervisor.existente(repo)]
        if local:
            raizes.append(supervisor.existente(local))
        return supervisor.Confinamento(escrita=tuple(raizes), rede=not local)

    # ------------------------------------------------------------- execução

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

        # O plano NÃO fornece refspec, URL, branch de destino nem credencial.
        for proibido in ("refspec", "url", "remote_url", "branch_destino",
                         "destination_branch", "force", "credential",
                         "credential_path"):
            if pedido.arg(proibido, None) is not None:
                raise ErroInvalido(
                    f"'{proibido}' não é aceito: destino, refspec e credencial "
                    "vêm da política, não do plano")

        destino = self.destino_de(
            texto_estrito(pedido.arg("remote_id"), "remote_id",
                          obrigatorio=True, maximo=64))
        origem = branch_valida(pedido.arg("source_branch"), "source_branch")
        alvo_branch = branch_valida(destino.branch_destino, "branch_destino")

        # SEGUNDA resolução, imediatamente antes do efeito. Entre a autorização
        # e esta linha, `.git/config` pode ter mudado.
        self.conferir_destino(repo, destino)

        refspec = f"refs/heads/{origem}:refs/heads/{alvo_branch}"
        argv = [self._git, "-C", str(repo), "--no-pager",
                *_NEUTRALIZAR, *_NEUTRALIZAR_PUSH,
                "push", "--no-force-with-lease", "--no-verify",
                destino.url, refspec]
        prazo = min(TIMEOUT_S, ctx.restante() or TIMEOUT_S)
        if prazo <= 0:
            raise ErroLimite("prazo do nó esgotado antes do push")
        p = supervisor.executar(argv, cwd=repo, env=ambiente_minimo(),
                                prazo=prazo,
                                confinamento=self.confinamento(repo, destino))
        if p.morto_por_timeout:
            raise ErroLimite(
                f"push excedeu {prazo:.1f}s — remoto que não responde não "
                "pendura o NOMOS")
        if p.returncode != 0:
            raise ErroRemoto(
                f"push falhou (rc={p.returncode}): "
                f"{p.stderr.decode('utf-8', 'replace')[:400]}")
        # O push escreve progresso e linhas `remote:` em stderr por rotina, e
        # nada disso é erro. Mas o lado remoto pode recusar objeto e a saída
        # ainda vir 0 ("remote unpack failed" foi medido no censo do C2c) —
        # publicação que não publicou não pode virar sucesso auditado.
        supervisor.conferir_saida(p.stderr, "push")
        self._auditar(ctx, "git.push", alvo=supervisor.canonicalizar(repo),
                      remote_id=destino.remote_id, url=destino.url,
                      origem=origem, destino=alvo_branch, sandbox=True,
                      rede=not self._local(destino),
                      classificacao=p.classificacao,
                      morto_por_timeout=p.morto_por_timeout)
        return CapabilityResult.sucesso(
            f"{origem} -> {destino.remote_id}/{alvo_branch}",
            efeito_aplicado=True)
