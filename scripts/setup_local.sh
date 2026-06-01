#!/bin/bash
# Prepare a fresh clone for local development.
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"

echo "🔧 Preparing FBM Pipeline local environment..."

mkdir -p "$PROJECT_DIR/data/products" "$PROJECT_DIR/logs"

if [ ! -f "$BACKEND_DIR/.env" ]; then
  cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
  echo "✅ Created backend/.env from backend/.env.example"
else
  echo "ℹ️  backend/.env already exists; left unchanged"
fi

if [ ! -d "$BACKEND_DIR/.venv" ]; then
  python3 -m venv "$BACKEND_DIR/.venv"
  echo "✅ Created backend/.venv"
else
  echo "ℹ️  backend/.venv already exists"
fi

source "$BACKEND_DIR/.venv/bin/activate"
pip install -r "$BACKEND_DIR/requirements.txt"

cd "$FRONTEND_DIR"
if [ -f package-lock.json ]; then
  npm install
else
  npm install
fi

echo ""
echo "✅ Local setup complete."
echo "   Edit backend/.env for API keys and real product paths when needed."
echo "   Start the app with: ./scripts/start.sh"
