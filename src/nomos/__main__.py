"""Permite `python -m nomos ...` — delega ao mesmo main() da CLI."""
from nomos.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
