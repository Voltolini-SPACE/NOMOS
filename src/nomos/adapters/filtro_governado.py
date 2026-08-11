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

import os
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
    # Identidade forte do executável entra em A5.3. O campo existe agora para
    # que a política já tenha onde guardá-la — declarar depois exigiria migrar
    # políticas em uso.
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
        if self.descendant_policy != "matar-arvore":
            raise ErroFiltro(
                f"descendant_policy {self.descendant_policy!r} não suportada "
                "— deixar descendente vivo não é opção de política")
        object.__setattr__(self, "canonical_executable", real)


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
