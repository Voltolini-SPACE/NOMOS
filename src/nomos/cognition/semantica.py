"""NOMOS cognition.semantica — busca por significado, 100% local e sem downloads.

Vetores por hashing de n-gramas de caracteres (3–5) com normalização L2 e
similaridade por cosseno. É simples de propósito: zero dependência, zero
rede, determinístico e auditável — encontra "aluguel do apartamento" quando
você busca "pagamento da moradia" razoavelmente bem para memórias curtas.

Honestidade: isto NÃO é um modelo de embeddings neural. É uma aproximação
local transparente. Quando um modelo local de embeddings for plugado (extra
opcional, download com aprovação), esta interface continua a mesma.
"""
from __future__ import annotations

import hashlib
import math
import re
import unicodedata

DIMENSOES = 512
_NGRAMAS = (3, 4, 5)

_SINONIMOS = {
    # normalização semântica mínima, transparente e em português
    "moradia": "casa", "apartamento": "casa", "residencia": "casa",
    "pagamento": "pagar", "pagou": "pagar", "paguei": "pagar",
    "compromisso": "tarefa", "pendencia": "tarefa", "afazer": "tarefa",
    "aniversario": "data", "vencimento": "data", "prazo": "data",
}


def _normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    palavras = re.findall(r"\w+", t)
    return " ".join(_SINONIMOS.get(p, p) for p in palavras)


def vetor(texto: str) -> list[float]:
    """Vetor L2-normalizado por hashing de n-gramas. Determinístico."""
    v = [0.0] * DIMENSOES
    t = f" {_normalizar(texto)} "
    for n in _NGRAMAS:
        for i in range(max(0, len(t) - n + 1)):
            ng = t[i:i + n]
            h = int.from_bytes(hashlib.blake2b(ng.encode(), digest_size=4).digest(),
                               "big")
            v[h % DIMENSOES] += 1.0
    norma = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norma for x in v]


def similaridade(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))


def ranquear(consulta: str, textos: list[str], k: int = 5,
             minimo: float = 0.05) -> list[tuple[int, float]]:
    """Índices dos `textos` mais parecidos com a consulta, com score."""
    vq = vetor(consulta)
    scores = [(i, similaridade(vq, vetor(t))) for i, t in enumerate(textos)]
    scores.sort(key=lambda p: p[1], reverse=True)
    return [(i, s) for i, s in scores[:k] if s >= minimo]
