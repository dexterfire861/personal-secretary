#!/usr/bin/env bash
# Launch the Personal Secretary: background task worker + API server together.
#
# Prerequisites:
#   - Ollama running (`ollama serve`) with the models in memory.py pulled.
#   - Python deps installed: venv/bin/pip install -r requirements.txt
#   - Frontend built once (optional; server falls back to static/ otherwise):
#       cd frontend && npm install && npm run build
#
# Stop with Ctrl-C — the worker is killed on exit.
set -euo pipefail
cd "$(dirname "$0")"
PY=venv/bin/python

echo "Starting background worker..."
"$PY" worker.py &
WORKER_PID=$!
trap 'echo "Stopping worker..."; kill "$WORKER_PID" 2>/dev/null || true' EXIT

echo "Starting API server on http://localhost:8000 ..."
"$PY" server.py
