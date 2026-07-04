"""NOMOS conversations.models — dados de conversa (F2)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Turn:
    id: int
    conversa_id: int
    ts: float
    role: str            # user | assistant | system | note
    text: str


@dataclass
class Conversation:
    id: int
    criada_em: float
    titulo: str = ""
    tags: list[str] = field(default_factory=list)
    motor: str = ""
    agente: str = ""
    fixada: bool = False
    usar_como_memoria: bool = True   # "não usar esta conversa como memória" => False
    ultima_ts: float = 0.0
    n_turnos: int = 0
