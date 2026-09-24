#!/bin/bash
set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

pause_before_close() {
  if [ -t 0 ]; then
    printf "\n"
    read -r -p "Press Return to close..." || true
  fi
}

printf "\nSoil MIR PLSR launcher\n"
printf "Platform: macOS\n\n"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  printf "Python 3 was not found.\n"
  printf "Install Python 3.10 or newer, then reopen run_app.command.\n"
  pause_before_close
  exit 1
fi

"$PYTHON_BIN" "$ROOT/scripts/launch_app.py"
code=$?

if [ "$code" -ne 0 ]; then
  printf "\nThe launcher exited with code %s.\n" "$code"
  pause_before_close
fi

exit "$code"
