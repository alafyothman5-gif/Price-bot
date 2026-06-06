#!/usr/bin/env bash
set -Eeuo pipefail
APP_DIR="/opt/pricebot"
SERVICE="pricebot.service"

if [[ "${PWD}" != "$APP_DIR" ]]; then
  echo "ERROR: يجب تشغيل deploy_pricebot_v18.sh من داخل $APP_DIR فقط." >&2
  exit 1
fi
if [[ -d "/opt/medmcq" ]]; then
  echo "INFO: MedMCQ موجود ومحمي. لن يتم لمسه أو إعادة تشغيله."
fi
if [[ ! -f "$APP_DIR/.env" ]]; then
  echo "ERROR: ملف .env غير موجود. انسخ .env.example إلى .env واملأ القيم أولاً." >&2
  exit 1
fi

bash "$APP_DIR/backup_pricebot.sh"

python3 -m venv "$APP_DIR/venv"
source "$APP_DIR/venv/bin/activate"
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

python - <<'PY'
import database
database.init_db()
print('PRICEBOT_SAFE_MIGRATION_OK')
PY

systemctl daemon-reload || true
systemctl restart "$SERVICE"
systemctl status "$SERVICE" --no-pager -l || true
sleep 2
curl -fsS http://127.0.0.1:8000/health

echo

echo "PRICEBOT_V18_DEPLOY_OK"
