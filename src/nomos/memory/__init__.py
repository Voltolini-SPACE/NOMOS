"""NOMOS Memory Engine V1 — memória persistente local-first para NOMOS/Claude Code.

Princípios (contrato MC28):
    LOCAL_FIRST · AUDITABLE · DRY_RUN_DEFAULT · FAIL_CLOSED · NO_NETWORK_RUNTIME ·
    NO_SECRET_STORAGE · ROLLBACK_READY

Este pacote é **autocontido**: usa apenas a biblioteca padrão do Python e não
importa o resto do NOMOS nem qualquer plugin externo. Isso garante isolamento
total (nada quebra se deps opcionais faltarem) e rollback trivial (apagar a
pasta ``nomos/memory`` remove o recurso inteiro sem efeitos colaterais).

Uso programático:
    >>> from nomos.memory import MemoryEngine
    >>> eng = MemoryEngine(base_dir="/tmp/mem")
    >>> r = eng.add("prefiro entregas com evidência")  # dry-run: não grava
    >>> r.dry_run, r.applied
    (True, False)
"""
from __future__ import annotations

from nomos.memory.engine import (
    MemoryEngine,
    AddResult,
    CompactResult,
    ValidationResult,
    VALID_PRIORITIES,
    VALID_SCOPES,
    VALID_SOURCES,
)
from nomos.memory.policy import REJECTION_CODE, PolicyDecision, evaluate, scan

__all__ = [
    "MemoryEngine",
    "AddResult",
    "CompactResult",
    "ValidationResult",
    "PolicyDecision",
    "evaluate",
    "scan",
    "REJECTION_CODE",
    "VALID_SOURCES",
    "VALID_SCOPES",
    "VALID_PRIORITIES",
    "__version__",
]

__version__ = "1.0.0"
ENGINE_ID = "NOMOS_MEMORY_ENGINE_V1"
