#!/usr/bin/env bash
# NOMOS rollback — restaura o backup mais recente do venv.
set -euo pipefail
PREFIX="${NOMOS_PREFIX:-$HOME/.local/share/nomos}"
BACKUPS="$PREFIX/backups"
LAST="$(ls -1t "$BACKUPS"/venv-*.tar.gz 2>/dev/null | head -1 || true)"
[[ -n "$LAST" ]] || { echo "FALHA: nenhum backup disponível para rollback." >&2; exit 1; }
echo "Restaurando: $LAST"
rm -rf "$PREFIX/venv"
tar -xzf "$LAST" -C "$PREFIX"
"$PREFIX/venv/bin/nomos" --version >/dev/null \
  || { echo "FALHA: rollback restaurou binário inválido." >&2; exit 1; }
echo "Rollback concluído. Versão ativa: $("$PREFIX/venv/bin/nomos" --version)"
