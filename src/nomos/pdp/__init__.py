"""NOMOS pdp — autoridade de decisão (PDP) e ponto de aplicação (PEP).

Separação deliberada: `decisor` DECIDE e não conhece adapters; `pep` APLICA e
não decide. Quem quiser efeito externo atravessa os dois, nesta ordem.

`autorizacao` guarda só a mecânica que torna a decisão comprovável
(canonicalização, HMAC, chaveiro com rotação, nonce anti-replay, atenuação).
"""
from nomos.pdp.autorizacao import (
    ArmazemNonce, Autorizacao, Chaveiro, ErroArmazem, ErroChaveiro, atenuar,
    e_atenuacao, hash_contrato,
)
from nomos.pdp.decisor import Decisao, Decisor, Efeito, Motivo, Pedido
from nomos.pdp.pep import NegadoPeloPEP, PontoDeAplicacao, proteger

__all__ = [
    "Autorizacao", "Chaveiro", "ArmazemNonce", "ErroArmazem", "ErroChaveiro",
    "hash_contrato", "e_atenuacao", "atenuar",
    "Decisor", "Decisao", "Pedido", "Efeito", "Motivo",
    "PontoDeAplicacao", "NegadoPeloPEP", "proteger",
]
