#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

pause_before_close() {
  if [ -t 0 ]; then
    printf "\n"
    read -r -p "Press Return to close..." || true
  fi
}

on_error() {
  code=$?
  trap - ERR
  printf "\nSoil MIR could not start.\n"
  printf "The command above failed with exit code %s.\n" "$code"
  printf "You can copy the Terminal output when reporting the problem.\n"
  pause_before_close
  exit "$code"
}
trap on_error ERR

printf "\nSoil MIR PLSR\n"
printf "Project: %s\n\n" "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  printf "Python 3 was not found.\n"
  printf "Install Python 3.10 or newer, then reopen run_app.command.\n"
  pause_before_close
  exit 1
fi

PYTHON_VERSION="$("$PYTHON_BIN" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  printf "Python %s was found, but Soil MIR requires Python 3.10 or newer.\n" "$PYTHON_VERSION"
  pause_before_close
  exit 1
fi
printf "[1/4] Python %s: OK\n" "$PYTHON_VERSION"

VENV="$ROOT/.venv"
STAMP="$VENV/.soil_mir_dependencies"

recreate_venv=0
if [ -x "$VENV/bin/python" ]; then
  if ! "$VENV/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
    recreate_venv=1
  fi
fi

if [ "$recreate_venv" -eq 1 ]; then
  printf "[2/4] Existing virtual environment uses an unsupported Python version; rebuilding it...\n"
  rm -rf "$VENV"
fi

if [ ! -x "$VENV/bin/python" ]; then
  printf "[2/4] Creating local Python environment...\n"
  "$PYTHON_BIN" -m venv "$VENV"
else
  printf "[2/4] Local Python environment: ready\n"
fi

source "$VENV/bin/activate"

if [ ! -f "$STAMP" ] || [ "$ROOT/pyproject.toml" -nt "$STAMP" ]; then
  printf "[3/4] Installing or updating Soil MIR dependencies...\n"
  printf "      First setup can take several minutes. Please keep this window open.\n"
  python -m pip install --upgrade pip
  python -m pip install -e ".[science]"
  touch "$STAMP"
  printf "[3/4] Dependencies: ready\n"
else
  printf "[3/4] Dependencies: already up to date\n"
fi

printf "[4/4] Starting Soil MIR...\n"
printf "      Keep this Terminal window open while using the app.\n"
printf "      Your browser should open automatically.\n\n"

trap - ERR
exec python -m streamlit run "$ROOT/app/Home.py"
