#!/usr/bin/env bash
# NOMOS uninstall — remove a plataforma; dados do usuário só com --purge confirmado.
set -euo pipefail
PREFIX="${NOMOS_PREFIX:-$HOME/.local/share/nomos}"
BIN_DIR="${NOMOS_BIN:-$HOME/.local/bin}"
DATA="${NOMOS_HOME:-$HOME/.nomos}"

rm -f "$BIN_DIR/nomos"
rm -rf "$PREFIX"
echo "Plataforma removida ($PREFIX e symlink)."

if [[ "${1:-}" == "--purge" ]]; then
  if [[ -t 0 ]]; then
    read -r -p "Digite exatamente 'APAGAR TUDO' para destruir os dados em $DATA: " CONF
    [[ "$CONF" == "APAGAR TUDO" ]] || { echo "Purga cancelada (confirmação incorreta)."; exit 1; }
  else
    echo "NEGADO (fail-closed): --purge exige terminal interativo." >&2; exit 3
  fi
  rm -rf "$DATA"
  echo "Dados do usuário destruídos ($DATA)."
else
  echo "Dados preservados em $DATA (use --purge para destruição definitiva)."
fi
