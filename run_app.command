#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python 3 was not found. Install Python 3 and reopen this launcher."
  read -r -p "Press Return to close..."
  exit 1
fi

VENV="$ROOT/.venv"
STAMP="$VENV/.soil_mir_dependencies"

if [ ! -x "$VENV/bin/python" ]; then
  "$PYTHON_BIN" -m venv "$VENV"
fi

source "$VENV/bin/activate"

if [ ! -f "$STAMP" ] || [ "$ROOT/pyproject.toml" -nt "$STAMP" ]; then
  python -m pip install --upgrade pip
  python -m pip install -e ".[science]"
  touch "$STAMP"
fi

exec python -m streamlit run "$ROOT/app/Home.py"
