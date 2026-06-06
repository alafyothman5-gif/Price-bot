#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="/opt/pricebot"
BACKUP_SCRIPT="./backup_pricebot.sh"
SERVICE_NAME="pricebot.service"

if [[ "$(pwd)" != "$APP_DIR" ]]; then
  echo "ERROR: run this script from $APP_DIR only. Refusing to touch other projects." >&2
  exit 1
fi
if [[ -d /opt/medmcq ]]; then
  echo "SAFE_CHECK: MedMCQ detected and will not be touched." >&2
fi
if [[ ! -f app.py || ! -f matcher_v4.py ]]; then
  echo "ERROR: not a PriceBot project directory." >&2
  exit 1
fi

mkdir -p /root/pricebot_backups
if [[ -x "$BACKUP_SCRIPT" ]]; then
  "$BACKUP_SCRIPT"
else
  tar --exclude='./venv' --exclude='./.venv' --exclude='./__pycache__' -czf "/root/pricebot_backups/pricebot_pre_v19_$(date +%Y%m%d_%H%M%S).tar.gz" .
fi

if [[ -f .env ]]; then
  echo "OK: preserving existing .env"
else
  echo "WARNING: .env not found. Copy .env.example to .env and fill secrets before production."
fi
if [[ -f pricebot.db ]]; then
  echo "OK: preserving existing pricebot.db"
else
  echo "INFO: pricebot.db not found; migrations will create an empty DB on first boot."
fi

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

python -m compileall -q .
python -m pytest -q
python acceptance_tests_v3.py
python acceptance_tests_v4.py
python acceptance_tests_final_v17.py
python acceptance_tests_final_v17_1.py
python acceptance_tests_final_v17_2.py
python acceptance_tests_final_v17_4.py
python acceptance_tests_final_v17_5.py
python acceptance_tests_final_v18.py
python acceptance_tests_final_v19.py

python - <<'PY'
import database
database.init_db()
database.ensure_v19_tables()
print('PRICEBOT_V19_SAFE_MIGRATION_OK')
PY

sudo systemctl daemon-reload || true
sudo systemctl restart "$SERVICE_NAME"
sudo systemctl status "$SERVICE_NAME" --no-pager -l || true
sleep 2
curl -fsS http://127.0.0.1:8000/health || { echo "ERROR: health check failed" >&2; exit 1; }
echo
echo "PRICEBOT_V19_DEPLOY_OK"
