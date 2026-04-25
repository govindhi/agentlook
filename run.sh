#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"

cleanup() { kill 0 2>/dev/null; }
trap cleanup EXIT

# --- Start backend ---
echo "🚀 Starting backend on http://localhost:8000 ..."
cd "$ROOT/backend"
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000 &

# --- Start frontend ---
echo "🚀 Starting frontend on http://localhost:5173 ..."
cd "$ROOT/frontend"
npm run dev &

wait
