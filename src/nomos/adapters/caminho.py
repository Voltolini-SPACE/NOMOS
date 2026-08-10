"""NOMOS adapters.caminho — resolução segura de caminho (ABSORPTION-03 / FASE 2).

Todo confinamento de filesystem do NOMOS passa por aqui. Um só lugar, porque
duas implementações de "é seguro?" acabam divergindo, e a divergência é o furo.

O que este módulo garante para um alvo, dadas raízes autorizadas:

- **canonicalização real**: `os.path.realpath` resolve `..`, `.`, links
  intermediários e o link final. Comparar strings sem resolver é o erro
  clássico — `/root/../etc/passwd` "começa com" `/root`;
- **anti-traversal**: depois de resolver, o caminho tem de estar sob alguma
  raiz, comparando por COMPONENTE. `/root-outro` não está sob `/root`;
- **anti-symlink-escape**: como comparamos o caminho JÁ resolvido, um symlink
  interno apontando para fora falha naturalmente. Para escrita/criação também
  recusamos que qualquer componente do caminho seja link que saia da raiz;
- **sem escape por caller**: não existe `unsafe=`, `skip_scope=` nem
  `follow_symlink=`. A assinatura simplesmente não tem por onde afrouxar.

Raízes vazias significam "sem restrição de caminho" — decisão herdada da
ABSORPTION-02 (leitura de alvo arbitrário é comportamento por desenho). Quem
quiser confinar passa raízes; o adapter não inventa uma sozinho nem relaxa a
que recebeu.
"""
from __future__ import annotations

import os
from pathlib import Path

from nomos.adapters.contrato import ErroEscopo, ErroInvalido


def _real(p: str | os.PathLike) -> str:
    """realpath sem levantar para caminho inexistente (resolve o que dá)."""
    return os.path.realpath(os.path.abspath(os.fspath(p)))


def _sob(caminho_real: str, raiz_real: str) -> bool:
    """Contenção por COMPONENTE — não por prefixo de string.

    `os.path.commonpath` normaliza os dois lados e compara componente a
    componente, então `/a/root-outro` não passa por `/a/root`.
    """
    if caminho_real == raiz_real:
        return True
    try:
        return os.path.commonpath([caminho_real, raiz_real]) == raiz_real
    except ValueError:
        return False            # drives/volumes diferentes (Windows)


def resolver(alvo: str, raizes: tuple[str, ...], *, para_escrita: bool = False) -> Path:
    """Caminho canônico seguro, ou `ErroEscopo`.

    `para_escrita=True` endurece: além de o destino final estar sob a raiz,
    nenhum componente EXISTENTE do caminho pode ser um link que saia dela —
    senão um `dir` symlinkado para fora receberia a escrita.
    """
    if not isinstance(alvo, str) or not alvo.strip():
        raise ErroInvalido("alvo vazio")
    if "\x00" in alvo:
        raise ErroInvalido("alvo com byte nulo")

    destino = _real(alvo)

    if not raizes:
        return Path(destino)          # sem escopo declarado: segue o desenho atual

    raizes_reais = [_real(r) for r in raizes if str(r).strip()]
    if not raizes_reais:
        raise ErroEscopo("nenhuma raiz utilizável no escopo")

    if not any(_sob(destino, r) for r in raizes_reais):
        raise ErroEscopo(
            f"caminho fora do escopo autorizado: {alvo!r} "
            f"(resolve para {destino!r})")

    if para_escrita:
        _recusar_escrita_via_symlink(alvo)
    return Path(destino)


def _recusar_escrita_via_symlink(alvo: str) -> None:
    """Escrita NÃO passa por link — nem por link que fica dentro da raiz.

    Nota honesta sobre o que este guard NÃO é: ele não existe para pegar
    symlink que sai do escopo. Esse caso já é pego pela checagem principal,
    porque `os.path.realpath` resolve links intermediários mesmo quando o
    componente final ainda não existe (verificado: `raiz/dir -> /externo` +
    alvo `raiz/dir/novo.txt` resolve para `/externo/novo.txt` e cai no
    `_sob`). Uma primeira versão deste módulo tinha uma checagem de cadeia
    para esse fim; a bateria de mutação mostrou que removê-la não quebrava
    NENHUM teste — era código morto, e código de segurança que nunca executa
    só produz confiança falsa. Foi removida.

    O que ficou é uma regra mais estrita e verificável: mutação através de
    symlink é recusada por princípio, mesmo dentro do escopo. Escrever em
    `raiz/atalho.txt -> raiz/real.txt` altera `real.txt` — efeito num alvo
    que o chamador não nomeou. Para mutar, nomeie o arquivo de verdade.
    """
    p = Path(alvo)
    if p.is_symlink():
        raise ErroEscopo(
            f"escrita através de symlink recusada: {alvo!r} — "
            "nomeie o arquivo real (o efeito recairia sobre outro alvo)")
    for ancestral in p.parents:
        if ancestral.is_symlink():
            raise ErroEscopo(
                f"componente do caminho é symlink: {str(ancestral)!r} — "
                "mutação através de link é recusada")
        if not str(ancestral) or str(ancestral) == ancestral.root:
            break


def dentro_do_escopo(alvo: str, raizes: tuple[str, ...]) -> bool:
    """Versão booleana, para filtrar listagem/glob sem levantar."""
    try:
        resolver(alvo, raizes)
        return True
    except (ErroEscopo, ErroInvalido):
        return False
