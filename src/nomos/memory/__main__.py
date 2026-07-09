"""Permite ``python -m nomos.memory`` como atalho para a CLI."""
from __future__ import annotations

from nomos.memory.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
