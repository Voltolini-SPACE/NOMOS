"""NOMOS adapters.filtro_governado — A5.2: quem escolhe o executável do filtro.

A5 provou que `filter.clean` escolhido pelo REPOSITÓRIO é execução arbitrária:
o repositório declara um executável no `.git/config` e o NOMOS o rodava. O
caminho padrão passou a NEGAR isso, e essa negação é definitiva.

Mas o caso legítimo existe — redator de segredo, normalizador, Git LFS. Este
módulo é onde ele volta a ser possível SEM devolver autoridade ao repositório:

    o repositório PEDE um filtro, por id
    o registry DECIDE se existe, qual binário roda, com que argumentos,
        lendo o quê, escrevendo onde, com que ambiente, prazo e rede

O contrato, que não se negocia:

    REPOSITORY_MAY_DECLARE_REQUIREMENT       = TRUE
    REPOSITORY_MAY_GRANT_EXECUTION_AUTHORITY = FALSE
    NOMOS_POLICY_IS_SOLE_EXECUTION_AUTHORITY = TRUE

A diferença é inteira, e é de titularidade: hoje o `.gitattributes` diz
`filter=redator` e o `.git/config` diz o que `redator` executa — as duas pontas
do lado não confiável. Aqui a primeira continua com o repositório (é só um
pedido) e a segunda passa para o NOMOS.

## Por que `argv` é FIXO na política

Um executável aprovado vira executor genérico se o chamador puder escolher os
argumentos: `/usr/bin/sed` é inofensivo até receber `-e 's/.*/rm -rf/e'`. A
política declara o argv COMPLETO; o repositório não contribui com nenhum
elemento dele. É por isso que `argv_policy` é uma tupla e não um template.

## O que este módulo AINDA NÃO faz

Resolução de identidade forte do executável (symlink swap, hardlink, TOCTOU)
é A5.3; sandbox dedicado é A5.5; ciclo de processo é A5.6. Aqui a autoridade é
do registry — e é só isso que este módulo promete. `canonical_executable` é
canonicalizado e sua existência é exigida, o que fecha o caso trivial e NÃO
fecha o caso adversarial: um teste explícito marca essa fronteira para que ela
não seja confundida com garantia.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass, field

from nomos.adapters.contrato import ErroInvalido

# Gramática de id. Deliberadamente estreita: o id vem do REPOSITÓRIO, então é
# entrada não confiável, e um id que possa conter caminho ou metacaractere
# convidaria a tentar resolvê-lo como caminho em algum ponto futuro.
_ID_OK = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
MAX_ID = 64


class ErroFiltro(ErroInvalido):
    """Pedido de filtro recusado. SEMPRE fail-closed."""


@dataclass(frozen=True)
class PoliticaDeFiltro:
    """A autoridade completa de UM filtro governado. Vem do NOMOS, não do repo.

    Todo campo aqui é uma decisão que o repositório NÃO toma. Se um campo
    novo for acrescentado no futuro, ele nasce com o mesmo dono.
    """
    filter_id: str
    canonical_executable: str
    argv_policy: tuple[str, ...] = ()
    read_roots: tuple[str, ...] = ()
    write_roots: tuple[str, ...] = ()
    environment_allowlist: tuple[str, ...] = ()
    network_policy: bool = False
    timeout: float = 30.0
    output_limit: int = 8 * 1024 * 1024
    descendant_policy: str = "matar-arvore"
    audit_policy: str = "sempre"
    # A AUTORIDADE DE EXECUÇÃO. Depois de A5.3 é este campo — e não
    # `canonical_executable` — que decide o que roda. O path externo fica como
    # PROVENIÊNCIA: serve para auditar de onde o binário veio, e para nada mais.
    managed_artifact: "ArtefatoGovernado | None" = None
    executable_identity: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        conferir_id(self.filter_id)
        if not self.canonical_executable:
            raise ErroFiltro(
                f"política {self.filter_id!r} sem executável — recuso: uma "
                "política sem binário não define autoridade nenhuma")
        real = os.path.realpath(self.canonical_executable)
        if not os.path.isabs(self.canonical_executable):
            raise ErroFiltro(
                f"executável de {self.filter_id!r} não é absoluto: "
                f"{self.canonical_executable!r} — caminho relativo seria "
                "resolvido por PATH, e PATH é influenciável")
        if not os.path.exists(real):
            raise ErroFiltro(
                f"executável de {self.filter_id!r} não existe: {real} — "
                "recuso na construção, não na execução")
        if self.timeout <= 0:
            raise ErroFiltro(f"timeout inválido em {self.filter_id!r}")
        conferir_argv(self.argv_policy, self.filter_id)
        if self.descendant_policy != "matar-arvore":
            raise ErroFiltro(
                f"descendant_policy {self.descendant_policy!r} não suportada "
                "— deixar descendente vivo não é opção de política")
        object.__setattr__(self, "canonical_executable", real)


    def executavel(self) -> str:
        """O caminho a EXECUTAR. Única porta, e ela verifica antes de abrir.

        `conferir()` acontece AQUI, e não num passo anterior, de propósito:
        quanto menor a distância lógica entre a verificação e o uso, menor a
        superfície acidental. Quem chamar este método recebe um caminho já
        conferido; quem quiser executar sem conferir teria de reimplementar a
        resolução — e o teste estrutural pega isso.

        Sem artefato importado NÃO HÁ EXECUÇÃO. O `canonical_executable` é
        proveniência: apontar o exec para ele reabriria exatamente o TOCTOU
        externo que A5.3 fechou.
        """
        if self.managed_artifact is None:
            raise ErroFiltro(
                f"filtro {self.filter_id!r} não tem artefato importado — o "
                "path externo é proveniência, não autoridade de execução; "
                "recuso em vez de executar a origem")
        self.managed_artifact.conferir()
        return self.managed_artifact.managed_path

    def comando(self) -> list[str]:
        """O argv COMPLETO a executar. Única porta, e ela não aceita nada.

        Repare na assinatura: não há parâmetro. Não existe canal por onde um
        chamador — muito menos o repositório — contribua com um elemento do
        argv. A5.2 decidiu QUEM escolhe o executável; A5.3, QUAL objeto; aqui,
        QUAIS ARGUMENTOS. Os três têm o mesmo dono.

        Um executável aprovado vira executor genérico no instante em que o
        argv aceita entrada: `/usr/bin/sed` é inofensivo até receber
        `-e 's/.*/rm -rf/e'`.
        """
        return [self.executavel(), *self.argv_policy]

    def ambiente(self) -> dict[str, str]:
        """Ambiente CONSTRUÍDO por allowlist, nunca herdado e nunca filtrado.

        Blocklist erra por omissão: bastaria um `SSH_AUTH_SOCK` esquecido, ou
        uma variável de provider que ainda não existe hoje, para o filtro
        herdar autoridade sem ninguém decidir isso. Aqui o ambiente nasce
        VAZIO e só recebe o que a política nomeou.

        `HOME` fica de fora de propósito: com HOME o filtro alcança
        `~/.gitconfig`, `~/.ssh` e material de credencial pelo caminho mais
        curto que existe. `PATH` também: quem resolve executável é a política
        (A5.2/A5.3), não a busca por PATH.
        """
        base = {"LANG": "C", "LC_ALL": "C"}
        for chave in self.environment_allowlist:
            valor = os.environ.get(chave)
            if valor is not None:
                base[chave] = valor
        return base

    def confinamento(self):
        """A autoridade do filtro EM EXECUÇÃO — mínima, e derivada da política.

        A5.2/A5.3/A5.4 decidiram QUEM executa, QUAL objeto e COM QUE
        argumentos. Nada disso limita o que o processo faz depois de nascer:
        um `sed` aprovado, íntegro e com argv fixo ainda leria `~/.ssh` se o
        confinamento não dissesse o contrário. Aprovado não é ilimitado.

        Reusa as primitivas que A2 (leitura), A3 (escrita), A5 (exec) e A6
        (negação) já construíram e provaram — um mecanismo paralelo só para
        filtros teria de reprovar tudo de novo, e divergiria na primeira
        correção aplicada a um lado só.
        """
        from nomos.adapters import supervisor
        if self.managed_artifact is None:
            raise ErroFiltro(
                f"filtro {self.filter_id!r} sem artefato — sem confinamento")
        leitura = tuple(self.read_roots) + (self.managed_artifact.managed_path,)
        return supervisor.Confinamento(
            escrita=tuple(self.write_roots),
            declara_sem_escrita=not self.write_roots,
            leitura=leitura,
            rede=self.network_policy,          # DENY por padrão
            exec_permitido=(self.managed_artifact.managed_path,),
        )

    def proveniencia(self) -> str:
        """De onde o binário veio. Auditoria — nunca execução."""
        return self.canonical_executable


# Argumento que o Git NÃO deve poder reinterpretar, e nomes de opção que
# transformam um filtro em executor de outro programa. A lista é POSITIVA e
# explícita: adivinhar padrão deixaria buraco, e `--exec`/`-e` provam que o
# perigo mora no nome da flag, não no formato dela.
_ARG_PROIBIDO = frozenset({
    "--exec", "--command", "--program", "--helper", "--shell",
    "--interpreter", "--config", "--rcfile", "--init-file", "--eval",
})
# Metacaracteres. NÃO ganham semântica (não há shell), mas um argumento que os
# carrega denuncia intenção — e um dia alguém pode acrescentar um shell.
_META = frozenset(";&|`$<>\n\r\x00")


def conferir_argv(argv: object, filter_id: str = "?") -> tuple[str, ...]:
    """Valida o argv da POLÍTICA na construção. Argv inválido nunca existe."""
    if not isinstance(argv, tuple):
        raise ErroFiltro(
            f"argv_policy de {filter_id!r} não é tupla: lista é mutável, e "
            "argv mutável é argv que alguém estende depois")
    for i, a in enumerate(argv):
        if not isinstance(a, str):
            raise ErroFiltro(f"argv[{i}] de {filter_id!r} não é str: {a!r}")
        if "\x00" in a:
            raise ErroFiltro(f"argv[{i}] de {filter_id!r} tem NUL")
        if a in _ARG_PROIBIDO:
            raise ErroFiltro(
                f"argv[{i}] de {filter_id!r} é {a!r} — flag que pede execução "
                "de OUTRO programa: o filtro aprovado viraria executor genérico")
    return argv


def conferir_id(bruto: object) -> str:
    """Valida o ÚNICO dado que o repositório fornece."""
    if not isinstance(bruto, str) or not bruto:
        raise ErroFiltro(f"filter_id inválido: {bruto!r}")
    if len(bruto) > MAX_ID:
        raise ErroFiltro(f"filter_id longo demais ({len(bruto)} > {MAX_ID})")
    ruins = sorted(set(bruto) - _ID_OK)
    if ruins:
        raise ErroFiltro(
            f"filter_id {bruto!r} fora da gramática (caracteres {ruins}) — "
            "id não é caminho e não pode parecer um")
    return bruto


class RegistroDeFiltros:
    """A autoridade. Só o que está aqui pode executar.

    Ausência de política é NEGAÇÃO, nunca fallback: um registry vazio recusa
    tudo, que é o comportamento correto para um sistema que ainda não decidiu.
    """

    def __init__(self, politicas: dict[str, PoliticaDeFiltro] | None = None):
        self._politicas: dict[str, PoliticaDeFiltro] = {}
        for pid, pol in (politicas or {}).items():
            self.registrar(pid, pol)

    def registrar(self, filter_id: str, politica: PoliticaDeFiltro) -> None:
        conferir_id(filter_id)
        if not isinstance(politica, PoliticaDeFiltro):
            raise ErroFiltro(
                f"política de {filter_id!r} não é PoliticaDeFiltro: "
                f"{type(politica).__name__} — dicionário solto viraria "
                "autoridade sem validação")
        if politica.filter_id != filter_id:
            raise ErroFiltro(
                f"chave {filter_id!r} != filter_id {politica.filter_id!r}")
        if filter_id in self._politicas:
            raise ErroFiltro(f"filtro {filter_id!r} já registrado")
        self._politicas[filter_id] = politica

    def resolver(self, requested_filter_id: object) -> PoliticaDeFiltro:
        """O pedido do repositório vira política, ou vira recusa.

        Este é o ponto onde a titularidade muda de lado. Tudo que entra aqui é
        não confiável; tudo que sai é decisão do NOMOS.
        """
        pid = conferir_id(requested_filter_id)
        try:
            return self._politicas[pid]
        except KeyError:
            raise ErroFiltro(
                f"filtro {pid!r} não está no registry — o repositório pode "
                "PEDIR um filtro, não autorizá-lo") from None

    def conhecidos(self) -> tuple[str, ...]:
        return tuple(sorted(self._politicas))


# ════════════════ A5.3 — artefato executável gerenciado pelo NOMOS ══════════
#
# A medição de A5.3.1 fechou a porta do modelo por identidade de path:
#
#     os.execve in os.supports_fd                  -> False   (sem fexecve)
#     exec via "/dev/fd/N" (com o fd preservado)   -> EACCES  (script E Mach-O)
#
# Não existe, neste host, primitive que vincule validação e uso ao MESMO objeto
# aberto. E o TOCTOU é real, medido: trocar o arquivo no path entre validar e
# executar roda o binário TROCADO (inode 437592231 -> 437592232, saída
# 'EXECUTOU_HOSTIL').
#
# A saída não é vencer a corrida — é tirar a corrida do caminho de execução. O
# executável externo é IMPORTADO uma vez, na aprovação, para um armazém privado
# do NOMOS. Depois disso o source é irrelevante em runtime: pode ser trocado,
# apagado, virar symlink para hostil. O NOMOS executa o artefato, não o source.
#
#     APPROVED_EXTERNAL_EXECUTABLE
#         -> import (copia + verifica + publica atomicamente)
#     NOMOS_CONTROLLED_EXECUTABLE_ARTIFACT
#         -> identidade imutável, endereçada por conteúdo
#     EXECUTION
#
# O gate deixa de afirmar a propriedade impossível ("o objeto validado no path
# externo é o objeto executado no path externo") e passa a afirmar a que é
# demonstrável: "o source externo NUNCA é executado depois da aprovação".

BLOCO = 1024 * 1024
MAX_ARTEFATO = 512 * 1024 * 1024


@dataclass(frozen=True)
class ArtefatoGovernado:
    """Executável sob custódia do NOMOS. Identidade endereçada por conteúdo."""
    artifact_id: str            # sha256 do conteúdo — o nome NÃO é confiável
    managed_path: str
    sha256: str
    size: int
    mode: int
    source_metadata: dict[str, object] = field(default_factory=dict)

    def conferir(self) -> None:
        """Revalida o artefato ANTES do uso.

        O armazém não é gravável pelo atacante do modelo de ameaça, mas
        corrupção, regressão e drift administrativo existem — e a verificação
        custa um hash. Nunca atualiza: divergência é DENY, não refresh.
        """
        try:
            atual, tamanho = _digerir(self.managed_path)
        except OSError as e:
            raise ErroFiltro(
                f"artefato {self.artifact_id} ilegível: {e}") from None
        if atual != self.sha256 or tamanho != self.size:
            raise ErroFiltro(
                f"artefato {self.artifact_id} DIVERGE do registrado "
                f"(sha {atual[:12]} != {self.sha256[:12]}) — recuso e NÃO "
                "atualizo: trocar binário exige nova aprovação")


def _digerir(caminho: str) -> tuple[str, int]:
    """sha256 + tamanho, lendo do descriptor JÁ aberto."""
    h, total = hashlib.sha256(), 0
    with open(caminho, "rb") as fh:
        while bloco := fh.read(BLOCO):
            total += len(bloco)
            if total > MAX_ARTEFATO:
                raise ErroFiltro(f"executável acima de {MAX_ARTEFATO} bytes")
            h.update(bloco)
    return h.hexdigest(), total


class ArmazemDeExecutaveis:
    """`NOMOS_EXEC_STORE` — a área privada de onde os filtros executam."""

    def __init__(self, raiz: str | os.PathLike):
        self.raiz = os.path.realpath(str(raiz))
        os.makedirs(self.raiz, mode=0o700, exist_ok=True)
        os.chmod(self.raiz, 0o700)

    def caminho_de(self, artifact_id: str) -> str:
        # Fan-out por prefixo: diretório único com milhares de entradas é
        # hostil a inspeção, e o prefixo não carrega significado nenhum.
        return os.path.join(self.raiz, artifact_id[:2], artifact_id)

    def importar(self, origem: str | os.PathLike) -> ArtefatoGovernado:
        """Copia o executável para o armazém e devolve identidade imutável.

        A publicação é ATÔMICA: escreve em temporário, verifica RELENDO o que
        foi gravado, e só então renomeia. Artefato parcial nunca fica visível —
        um `os.replace` só acontece depois de o conteúdo já estar conferido.
        """
        origem_real = os.path.realpath(str(origem))
        try:
            st = os.stat(origem_real)
        except OSError as e:
            raise ErroFiltro(f"origem ilegível: {e}") from None
        if not stat.S_ISREG(st.st_mode):
            raise ErroFiltro(
                f"origem {origem_real} não é arquivo regular — diretório, "
                "device ou fifo não são executáveis governáveis")

        try:
            sha_origem, tamanho = _digerir(origem_real)
        except OSError as e:
            # Mesmo motivo do bloco da cópia: a origem pode sumir a qualquer
            # instante. Toda falha desta fronteira sai como ErroFiltro — o
            # contrato do módulo é um só, e exceção fora dele é exceção que o
            # chamador não sabe tratar.
            raise ErroFiltro(f"origem ilegível: {e}") from None
        artifact_id = sha_origem
        destino = self.caminho_de(artifact_id)
        os.makedirs(os.path.dirname(destino), mode=0o700, exist_ok=True)

        fd, temporario = tempfile.mkstemp(dir=os.path.dirname(destino),
                                          prefix=".importando-")
        try:
            try:
                with os.fdopen(fd, "wb") as saida, open(origem_real, "rb") as ent:
                    shutil.copyfileobj(ent, saida, BLOCO)
                    saida.flush()
                    os.fsync(saida.fileno())
            except OSError as e:
                # A origem pode sumir ENTRE o digest e a cópia — medido na
                # bateria de concorrência. Sem esta tradução escapava um
                # `FileNotFoundError` cru, e quem trata o contrato documentado
                # (`ErroFiltro`) NÃO o pegaria: falha fora do contrato é falha
                # que o chamador não sabe tratar.
                raise ErroFiltro(f"origem sumiu durante a cópia: {e}") from None
            os.chmod(temporario, 0o500)          # r-x, e NÃO gravável

            # RELER o que foi gravado. Comparar com o hash da origem não basta:
            # a origem pode ter mudado ENTRE o digest e a cópia, e o que importa
            # é o que está no armazém.
            sha_gravado, tam_gravado = _digerir(temporario)
            if tam_gravado != tamanho or sha_gravado != sha_origem:
                raise ErroFiltro(
                    "conteúdo mudou durante a importação "
                    f"({sha_origem[:12]} -> {sha_gravado[:12]}) — a origem foi "
                    "substituída no meio da cópia; recuso e não publico")

            if os.path.exists(destino):
                # Endereçado por conteúdo: mesmo id => mesmos bytes. Já existir
                # é deduplicação, não conflito. Mas confere antes de confiar.
                existente, _ = _digerir(destino)
                if existente != sha_gravado:
                    raise ErroFiltro(
                        f"colisão real em {artifact_id} — armazém corrompido")
                os.unlink(temporario)
            else:
                os.replace(temporario, destino)  # publicação ATÔMICA
            temporario = None
        finally:
            if temporario and os.path.exists(temporario):
                os.unlink(temporario)

        return ArtefatoGovernado(
            artifact_id=artifact_id, managed_path=destino, sha256=sha_origem,
            size=tamanho, mode=0o500,
            source_metadata={"source_path": origem_real,     # só auditoria
                             "source_inode": st.st_ino,
                             "source_size": st.st_size})
