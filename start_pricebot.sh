#!/usr/bin/env bash
set -euo pipefail
cd /opt/pricebot
PORT="${PORT:-8000}"
exec /opt/pricebot/venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port "$PORT"
