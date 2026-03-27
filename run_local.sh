#!/usr/bin/env bash
# run_local.sh — Start both backend and frontend in one terminal session
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "════════════════════════════════════════════"
echo "  TrustFeed — Local Dev Startup"
echo "════════════════════════════════════════════"

# ── Check Ollama ──────────────────────────────────────────────────────────
if ! command -v ollama &> /dev/null; then
  echo "⚠  Ollama not found. Install from https://ollama.ai then run:"
  echo "   ollama pull llama3"
  echo "   ollama serve"
  echo ""
fi

# ── Backend ───────────────────────────────────────────────────────────────
echo "→ Starting backend…"
cd "$ROOT/backend"

if [ ! -d "venv" ]; then
  echo "  Creating Python venv…"
  python3 -m venv venv
fi

source venv/bin/activate
pip install -q -r requirements.txt

# Install Playwright browsers if needed
python -c "from playwright.sync_api import sync_playwright; sync_playwright().start()" 2>/dev/null \
  || playwright install chromium --with-deps

uvicorn main:app --reload --port 8000 &
BACKEND_PID=$!
echo "  Backend PID: $BACKEND_PID"

# ── Frontend ──────────────────────────────────────────────────────────────
echo "→ Starting frontend…"
cd "$ROOT/frontend"

if [ ! -d "node_modules" ]; then
  echo "  Installing npm packages…"
  npm install
fi

npm run dev &
FRONTEND_PID=$!
echo "  Frontend PID: $FRONTEND_PID"

echo ""
echo "════════════════════════════════════════════"
echo "  Dashboard: http://localhost:5173"
echo "  API docs:  http://localhost:8000/docs"
echo "════════════════════════════════════════════"
echo "  Press Ctrl+C to stop both services"
echo ""

# ── Cleanup on exit ───────────────────────────────────────────────────────
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; echo 'Stopped.'" EXIT
wait
