#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
root="$PWD"
install=false
initialize=false
for arg in "$@"; do
  case "$arg" in
    --install) install=true ;;
    --initialize) initialize=true ;;
    *) printf 'Usage: bash deploy/start-local.sh [--install] [--initialize]\n'; exit 2 ;;
  esac
done
if "$install"; then
  if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; fi
  .venv/bin/python -m pip install -r backend/requirements.txt -c backend/requirements.lock.txt
  (cd frontend && npm ci)
fi
if [ ! -x .venv/bin/python ]; then printf 'Run with --install first.\n'; exit 1; fi
cd backend
../.venv/bin/python -m alembic upgrade head
if "$initialize"; then ../.venv/bin/python -m app.cli create-admin --username admin; fi
mkdir -p "$root/.local"
../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log > "$root/.local/api.log" 2>&1 &
api_pid=$!
cd "$root/frontend"
node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173 --strictPort > "$root/.local/frontend.log" 2>&1 &
web_pid=$!
trap 'kill "$api_pid" "$web_pid" 2>/dev/null || true' EXIT
printf 'Open http://127.0.0.1:5173 — Ctrl+C stops both local servers.\n'
wait
