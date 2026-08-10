"""NOMOS adapters.wiring — liga os adapters ao runtime governado (ABSORPTION-03).

Módulo existir não é capacidade existir. Enquanto os adapters não estiverem no
`RegistroCapacidades`, eles são camada pronta e nada mais: o planejador não os
conhece, o grafo os recusa, o PDP não tem o que autorizar. Este módulo é o elo
que os torna operacionais — pelo caminho governado, nunca por atalho.

## Por que capacidade DINÂMICA e não nativa

A allowlist de 8 ferramentas (`agents.manifest.FERRAMENTAS`) é invariante de
segurança do produto: "agente não é bypass". Dobrar essa lista mudaria um
contrato congelado e ampliaria a superfície nativa de uma vez.

O registro dinâmico (NH-001) existe exatamente para isto, e é ele próprio
governado: registrar é ato `A5_SKILL_INSTALL`, passa pelo `policy.gate`, exige
aprovador, é auditado, e nativa não pode ser sombreada. Uma capacidade nova
entra pela porta da frente, com aprovação — não por edição de constante.

## O que o executor registrado faz

Ele NÃO é o adapter cru. É uma ponte que:
1. monta `CapabilityContext` por `de_registro()` — risco e idempotência saem do
   registro, jamais do chamador;
2. propaga o escopo de caminho e o deadline do nó;
3. chama o adapter;
4. traduz `CapabilityResult` para o valor que o orquestrador espera, e
   `ErroCapacidade` para exceção (o orquestrador já trata falha de nó).

Nenhuma autoridade nova nasce aqui: quem decidiu se o nó podia executar foi o
gate do kernel + o PDP, antes.
"""
from __future__ import annotations

import time

from nomos.adapters.contrato import CapabilityContext, CapabilityRequest
from nomos.adapters.filesystem import FilesystemAdapter
from nomos.kernel.policy import Category

# Categoria de política de cada capacidade de filesystem. É AQUI que o risco é
# declarado — uma vez, no registro — e não no adapter nem no plano.
CATEGORIAS_FS: dict[str, Category] = {
    "fs-ler": Category.READ_LOCAL,
    "fs-listar": Category.READ_LOCAL,
    "fs-metadados": Category.READ_LOCAL,
    "fs-escrever": Category.WRITE_LOCAL,
    "fs-editar": Category.WRITE_LOCAL,
    "fs-criar-dir": Category.WRITE_LOCAL,
    "fs-mover": Category.WRITE_LOCAL,
    "fs-apagar": Category.WRITE_LOCAL,
}

# Repetir é seguro? Só para leitura. Escrita/edição/move/delete NÃO são
# idempotentes — repetir uma remoção às cegas é o tipo de "recuperação" que
# destrói dado. É esta tabela que autoriza retry, nunca o plano.
IDEMPOTENTES_FS = {"fs-ler", "fs-listar", "fs-metadados"}


def _ponte(adapter, nome: str, registro, *, raizes=(), audit=None,
           timeout_s: float | None = None):
    """Executor registrado: params do nó → adapter, com contexto derivado."""
    def _executar(**params):
        deadline = (time.monotonic() + timeout_s) if timeout_s else None
        ctx = CapabilityContext.de_registro(
            registro, nome, params.pop("_sujeito", "runtime-governado"),
            raizes=raizes, deadline_monotonic=deadline, audit=audit)
        pedido = CapabilityRequest(
            capacidade=nome,
            alvo=str(params.get("alvo", "") or ""),
            argumentos=dict(params))
        resultado = adapter.executar(pedido, ctx)
        return resultado.valor if resultado.valor is not None else resultado.detalhe
    _executar.__name__ = f"adapter_{nome}"
    _executar.__qualname__ = f"adapter_{nome}"
    return _executar


def registrar_filesystem(registro, *, raizes=(), audit=None,
                         timeout_s: float | None = 30.0,
                         apenas_leitura: bool = False) -> list[str]:
    """Registra as capacidades de filesystem. Devolve os nomes registrados.

    `apenas_leitura=True` registra só as três de leitura — atenuação legítima
    para contextos que não devem mutar nada.

    Cada `registrar()` passa pelo gate A5 do kernel; sem política ou sem
    aprovador, nada é registrado (fail-closed). Um `ErroRegistro` de "já
    registrada" é tratado como idempotência do próprio wiring, não como falha.
    """
    from nomos.orquestracao.registro import ErroRegistro

    adapter = FilesystemAdapter()
    nomes = sorted(IDEMPOTENTES_FS) if apenas_leitura else sorted(CATEGORIAS_FS)
    registrados = []
    for nome in nomes:
        try:
            registro.registrar(
                nome, CATEGORIAS_FS[nome],
                _ponte(adapter, nome, registro, raizes=raizes, audit=audit,
                       timeout_s=timeout_s),
                origem="adapters.filesystem",
                idempotente=nome in IDEMPOTENTES_FS)
            registrados.append(nome)
        except ErroRegistro as exc:
            if "já registrada" in str(exc):
                registrados.append(nome)
                continue
            raise
    return registrados
