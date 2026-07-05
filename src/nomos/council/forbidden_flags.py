"""Motor Council — contrato ÚNICO de flags proibidas do dry-run (MC24).

Fonte única e testável do conjunto de flags que o dry-run do Conselho recusa
**fail-closed**, tanto na CLI (`nomos conselho simular`) quanto no chat
(`/conselho simular`).

Contexto (a divergência que a MC24 elimina): até a MC23 a CLI listava **8**
flags proibidas e o chat **10** — o chat adicionava `--vault-real` e
`--engine-real`. Na prática isso **nunca** abriu execução real (as duas
superfícies já recusam qualquer flag desconhecida fail-closed), mas era uma
inconsistência de contrato: a mesma flag (`--vault-real`) era classificada como
"proibida" no chat e apenas "desconhecida" na CLI. A MC24 reconcilia as duas
superfícies no **mesmo** conjunto de 10 (decisão A), com esta fonte única.

Invariantes de segurança deste contrato:

- uma flag proibida **nunca** liga execução real, cloud, rede, subprocess,
  policy/audit/vault reais ou persistência;
- a detecção é por **igualdade estrita** de string — nunca por prefixo/substring
  —, então flags parecidas mas legítimas (`--realmente`, `--enabled`,
  `--cloudy`) não geram falso positivo (elas seguem recusadas como
  *desconhecidas* pelo parser de cada superfície, não como *proibidas*);
- quem chama **nunca** ecoa a flag/token de volta ao usuário; este módulo só
  responde "é proibida?" e nunca imprime nada.

Pureza (provada por AST em `tests/council/test_forbidden_flags_contract.py`):
define apenas um `frozenset` e funções puras; não importa rede, subprocess,
threading, asyncio, cloud, motor, harness, nem policy/audit/vault reais do
kernel; não toca filesystem/env; não usa relógio nem aleatoriedade; não
serializa nem faz dump de objeto algum.
"""
from __future__ import annotations

from collections.abc import Iterable

# --------------------------------------------------------------------------
# Contrato único (decisão A da MC24): as 10 flags que o dry-run do Conselho
# recusa fail-closed em QUALQUER superfície (CLI e chat). A semântica é de
# conjunto (pertencimento por igualdade estrita), não de ordem.
# --------------------------------------------------------------------------
FORBIDDEN_FLAGS: frozenset[str] = frozenset({
    "--real",         # ligar execução real
    "--enable",       # habilitar execução real (inglês)
    "--ativar",       # habilitar execução real (pt-BR)
    "--force",        # forçar/pular salvaguardas
    "--unsafe",       # desligar salvaguardas
    "--cloud",        # sair para nuvem/rede
    "--audit-real",   # gravar auditoria real
    "--policy-real",  # aplicar policy real
    "--vault-real",   # abrir a caixa-forte real
    "--engine-real",  # ligar o motor real
})


def is_forbidden_flag(token: object) -> bool:
    """Diz se `token` é **exatamente** uma flag proibida do contrato.

    Comparação por igualdade estrita de string (pertencimento no `frozenset`) —
    nunca por prefixo/substring —, para não gerar falso positivo em flags
    parecidas mas legítimas (ex.: ``--realmente``, ``--enabled``, ``--cloudy``,
    ``--forcado``). Não ecoa nada; só devolve um booleano.
    """
    return token in FORBIDDEN_FLAGS


def find_forbidden(tokens: Iterable[object]) -> str | None:
    """Devolve a **primeira** flag proibida encontrada em `tokens`, ou ``None``.

    Varre da esquerda para a direita (determinístico), de modo que combinações
    de flags proibidas são detectadas pela primeira ocorrência. Não imprime nem
    ecoa nada: quem chama decide a mensagem fixa/amigável e **nunca** inclui a
    flag na saída.
    """
    for tok in tokens or ():
        if tok in FORBIDDEN_FLAGS:
            # `tok` pertence ao contrato fixo (não é conteúdo do usuário); ainda
            # assim, o chamador é responsável por não ecoá-lo.
            return tok  # type: ignore[return-value]
    return None
