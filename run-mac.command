#!/bin/bash
# Double-click me in Finder to run OutLoud from source on a Mac.
# Needs Python 3 (https://www.python.org/downloads/ — the installer includes Tk).
cd "$(dirname "$0")"
if command -v uv >/dev/null 2>&1; then
  exec uv run outloud "$@"
fi
if [ ! -x .venv/bin/python ]; then
  echo "First run: setting up (about a minute)…"
  python3 -m venv .venv && .venv/bin/pip install -q -e . || { echo "Setup failed. Install Python 3 from python.org and try again."; read -r; exit 1; }
fi
exec .venv/bin/python -m outloud "$@"
