#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"

# --- Backend setup ---
echo "📦 Setting up backend..."
cd "$ROOT/backend"
python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt

# --- Frontend setup ---
echo "📦 Setting up frontend..."
cd "$ROOT/frontend"
npm install

echo ""
echo "✅ Setup complete! Run the dashboard with:"
echo "   ./run.sh"
