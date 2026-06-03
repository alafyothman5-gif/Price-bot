#!/usr/bin/env bash
set -e
cd /opt/pricebot

# Use uvicorn import mode so all patch code after the __main__ block is loaded.
if [ -f app.py ] && grep -q "FastAPI" app.py; then
  exec /opt/pricebot/venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8090
elif [ -f main.py ] && grep -q "FastAPI" main.py; then
  exec /opt/pricebot/venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8090
elif [ -f server.py ] && grep -q "FastAPI" server.py; then
  exec /opt/pricebot/venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port 8090
else
  echo "ERROR: لم أجد app.py أو main.py أو server.py"
  exit 1
fi
