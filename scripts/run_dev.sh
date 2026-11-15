#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

if [ ! -f "$ROOT_DIR/.env" ] && [ -f "$ROOT_DIR/.env.example" ]; then
  echo "[ASTRA-Med] Creating .env from .env.example..."
  cp "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
fi

if [ ! -d "$BACKEND_DIR/.venv" ]; then
  echo "[ASTRA-Med] Creating Python virtual environment in backend/.venv..."
  python3 -m venv "$BACKEND_DIR/.venv"
  "$BACKEND_DIR/.venv/bin/pip" install --upgrade pip
  "$BACKEND_DIR/.venv/bin/pip" install -r "$BACKEND_DIR/requirements.txt"
fi

echo "[ASTRA-Med] Starting FastAPI backend on http://127.0.0.1:8000 (Swagger: /docs)..."
(cd "$BACKEND_DIR" && "$BACKEND_DIR/.venv/bin/uvicorn" app.main:app --reload --host 0.0.0.0 --port 8000) &
BACK_PID=$!

if [ -f "$FRONTEND_DIR/package.json" ]; then
  if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    echo "[ASTRA-Med] Installing frontend dependencies..."
    (cd "$FRONTEND_DIR" && npm install)
  fi
  echo "[ASTRA-Med] Starting Vite frontend on http://127.0.0.1:5173..."
  (cd "$FRONTEND_DIR" && npm run dev -- --host 0.0.0.0 --port 5173) &
  FRONT_PID=$!
else
  echo "[ASTRA-Med] Frontend not initialized yet (Role 1 workspace in frontend/). Backend running standalone."
  FRONT_PID=""
fi

cleanup() {
  echo "[ASTRA-Med] Shutting down..."
  kill "$BACK_PID" 2>/dev/null || true
  if [ -n "$FRONT_PID" ]; then
    kill "$FRONT_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

wait "$BACK_PID"
