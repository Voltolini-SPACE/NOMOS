"""NOMOS adapters — a camada de efeito externo governado (ABSORPTION-03).

Um adapter é o último elo antes do mundo mudar. Ele recebe contexto JÁ
autorizado e não decide nada sobre autoridade — risco e idempotência vêm
carimbados do registro; escopo vem do PDP.
"""
from nomos.adapters.contrato import (
    Adapter, CapabilityContext, CapabilityRequest, CapabilityResult,
    EfeitoTimeout, ErroCapacidade, ErroConflito, ErroEscopo, ErroInvalido,
    ErroLimite, ErroNaoEncontrado, ErroPermissao, ErroTimeout,
    versao_de_capacidade,
)

__all__ = [
    "Adapter", "CapabilityRequest", "CapabilityContext", "CapabilityResult",
    "ErroCapacidade", "ErroEscopo", "ErroNaoEncontrado", "ErroPermissao",
    "ErroLimite", "ErroInvalido", "ErroTimeout", "ErroConflito",
    "EfeitoTimeout", "versao_de_capacidade",
]
