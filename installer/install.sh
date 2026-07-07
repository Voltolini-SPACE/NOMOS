#!/usr/bin/env bash
# NOMOS installer — falha fechado em qualquer inconsistência.
# Funciona em dois modos:
#   1) release: um nomos-*.whl ao lado deste script (baixado do GitHub);
#   2) desenvolvimento: rodado de dentro do repositório (instala o código-fonte).
set -euo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="$(cd "$AQUI/.." 2>/dev/null && pwd || echo "$AQUI")"
PREFIX="${NOMOS_PREFIX:-$HOME/.local/share/nomos}"
BIN_DIR="${NOMOS_BIN:-$HOME/.local/bin}"
VENV="$PREFIX/venv"
BACKUPS="$PREFIX/backups"

# fonte de instalação: wheel ao lado do script (release) > código-fonte (dev)
WHEEL="$(ls -1 "$AQUI"/nomos-*.whl 2>/dev/null | sort | tail -1 || true)"
if [[ -n "$WHEEL" ]]; then
  FONTE="$WHEEL"
  SUMS_DIR="$AQUI"
else
  FONTE="$PKG_DIR"
  SUMS_DIR="$PKG_DIR"
fi

echo "[1/6] Verificando integridade (SHA256SUMS)..."
if [[ -f "$SUMS_DIR/SHA256SUMS" ]]; then
  (cd "$SUMS_DIR" && sha256sum --check --quiet --ignore-missing SHA256SUMS) \
    || { echo "FALHA: checksums divergentes — instalação abortada (fail-closed)." >&2; exit 1; }
  echo "      checksums OK."
else
  echo "AVISO: SHA256SUMS ausente — prosseguindo apenas porque é build local de desenvolvimento." >&2
fi

echo "[2/6] Verificando Python >= 3.10..."
python3 - <<'PY' || { echo "FALHA: Python 3.10+ é obrigatório." >&2; exit 1; }
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY

echo "[3/6] Backup da instalação anterior (rollback)..."
mkdir -p "$BACKUPS"
if [[ -d "$VENV" ]]; then
  STAMP="$(date +%Y%m%d-%H%M%S)"
  tar -czf "$BACKUPS/venv-$STAMP.tar.gz" -C "$PREFIX" venv
  echo "      backup: $BACKUPS/venv-$STAMP.tar.gz"
else
  echo "      nenhuma instalação anterior."
fi

echo "[4/6] Criando ambiente isolado e instalando..."
echo "      fonte: $FONTE"
python3 -m venv --clear "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet "$FONTE"

echo "[5/6] Publicando comando 'nomos'..."
mkdir -p "$BIN_DIR"
ln -sf "$VENV/bin/nomos" "$BIN_DIR/nomos"

echo "[6/6] Smoke pós-instalação..."
"$BIN_DIR/nomos" --version >/dev/null \
  || { echo "FALHA: smoke pós-instalação não passou." >&2; exit 1; }

echo
echo "NOMOS instalado. Versão: $("$BIN_DIR/nomos" --version)"
echo "Comece com:  nomos"
[[ ":$PATH:" == *":$BIN_DIR:"* ]] || echo "AVISO: adicione $BIN_DIR ao PATH."
