#!/usr/bin/env bash
# macOS / Linux launcher
set -e
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "Creating the Python environment once..."
  python3 -m venv .venv
  ./.venv/bin/python -m pip install --quiet --upgrade pip
  ./.venv/bin/python -m pip install --quiet -r requirements.txt
fi

if [ ! -f "data/nivora.db" ]; then
  echo "First run: creating the demo shop..."
  ./.venv/bin/python -m scripts.seed_demo
fi

echo "NIVORA → http://localhost:8000   (demo@nivora.my / nivora-demo-2026)"
exec ./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
