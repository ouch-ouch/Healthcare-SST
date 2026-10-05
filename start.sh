#!/usr/bin/env bash
# One-click setup + launch for the Harborview Source of Truth web UI.
# Creates the venv and installs dependencies only if they don't already exist,
# so re-running this is always safe and fast.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "Setting up environment (first run only)..."
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
fi

echo "Starting Harborview Source of Truth at http://127.0.0.1:5050"
.venv/bin/python app.py &
SERVER_PID=$!
sleep 1

if command -v open >/dev/null 2>&1; then
  open "http://127.0.0.1:5050"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "http://127.0.0.1:5050"
fi

wait "$SERVER_PID"
