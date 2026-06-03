#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/pricebot"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TS="$(date +%Y%m%d_%H%M%S)"

printf '=== PriceBot GitHub Deploy: Safe Upload + Safe Image/Text Match + AI Key Reset ===\n'
printf 'Repo: %s\n' "$REPO_DIR"
printf 'App : %s\n' "$APP_DIR"

if [ ! -f "$REPO_DIR/app.py" ]; then
  echo "ERROR: app.py غير موجود داخل الريبو"
  exit 1
fi

mkdir -p "$APP_DIR"

printf '\n1) Backup current server copy, including products/database/orders/secrets...\n'
if [ -d "$APP_DIR" ]; then
  tar \
    --exclude="$APP_DIR/venv" \
    --exclude="$APP_DIR/__pycache__" \
    --exclude="$APP_DIR/**/__pycache__" \
    -czf "/root/pricebot_BACKUP_BEFORE_GITHUB_DEPLOY_$TS.tar.gz" \
    -C /opt pricebot 2>/dev/null || true
  ls -lh "/root/pricebot_BACKUP_BEFORE_GITHUB_DEPLOY_$TS.tar.gz" 2>/dev/null || true
fi

printf '\n2) Copy code only. Products/database/orders/.env will NOT be deleted...\n'
cp "$REPO_DIR/app.py" "$APP_DIR/app.py"
cp "$REPO_DIR/requirements.txt" "$APP_DIR/requirements.txt"
cp "$REPO_DIR/start_pricebot.sh" "$APP_DIR/start_pricebot.sh"
chmod +x "$APP_DIR/start_pricebot.sh"

# Copy helper scripts/docs only. Do not overwrite live data.
for f in SET_OPENROUTER_KEY.sh CHECK_OPENROUTER_KEY.sh CLEAN_AI_KEYS.sh products_template.csv .env.example README_START_HERE.md README_DEPLOY_AR.md README_AI_OPENROUTER_AR.md README_SAFE_MATCH_AR.md README_SAFE_UPLOAD_AR.md; do
  [ -f "$REPO_DIR/$f" ] && cp "$REPO_DIR/$f" "$APP_DIR/$f"
done
chmod +x "$APP_DIR/SET_OPENROUTER_KEY.sh" "$APP_DIR/CHECK_OPENROUTER_KEY.sh" "$APP_DIR/CLEAN_AI_KEYS.sh" 2>/dev/null || true

if [ ! -f "$APP_DIR/.env" ]; then
  echo "WARNING: /opt/pricebot/.env غير موجود. سيتم إنشاء ملف مثال، ويجب وضع توكن واتساب الحقيقي داخله."
  cp "$REPO_DIR/.env.example" "$APP_DIR/.env"
  chmod 600 "$APP_DIR/.env"
fi

if [ ! -f "$APP_DIR/products.csv" ]; then
  echo "products.csv غير موجود؛ سيتم إنشاء قالب فارغ فقط. هذا لا يحدث إذا كانت منتجاتك موجودة."
  cp "$REPO_DIR/products_template.csv" "$APP_DIR/products.csv"
fi

if [ ! -f "$APP_DIR/orders.csv" ]; then
  printf '\ufefftime,phone,product,price,available,notes,message,status\n' > "$APP_DIR/orders.csv"
fi

printf '\n3) Reset ALL old AI keys/settings now, but preserve WhatsApp tokens/products/database...\n'
if [ -f "$APP_DIR/CLEAN_AI_KEYS.sh" ]; then
  bash "$APP_DIR/CLEAN_AI_KEYS.sh"
else
  echo "WARNING: CLEAN_AI_KEYS.sh not found; skipping AI key reset."
fi


printf '\n3b) Clear old image cache to remove any previously wrong image matches...\n'
python3 - <<'CLEARCACHEPY'
import sqlite3, json
from pathlib import Path
app = Path('/opt/pricebot')
db = app / 'pricebot.db'
if db.exists():
    try:
        con = sqlite3.connect(str(db))
        con.execute("DELETE FROM memory_entries WHERE category='image_cache'")
        con.commit()
        con.close()
        print('Cleared image_cache from', db)
    except Exception as e:
        print('Image cache DB clear warning:', e)
mem = app / 'memory.json'
if mem.exists():
    try:
        data = json.loads(mem.read_text(encoding='utf-8', errors='ignore') or '{}')
        if isinstance(data, dict):
            data['image_cache'] = {}
            mem.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            print('Cleared image_cache from memory.json')
    except Exception as e:
        print('Image cache JSON clear warning:', e)
CLEARCACHEPY

printf '\n4) Install/update Python environment...\n'
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv python3-pip >/dev/null
cd "$APP_DIR"
if [ ! -d venv ]; then
  python3 -m venv venv
fi
./venv/bin/python -m pip install --upgrade pip wheel setuptools >/dev/null
./venv/bin/pip install -r requirements.txt

printf '\n5) Compile check...\n'
./venv/bin/python -m py_compile app.py

printf '\n6) Install pricebot systemd service using uvicorn app:app on port 8090...\n'
cat > /etc/systemd/system/pricebot.service <<'SERVICE'
[Unit]
Description=PriceBot WhatsApp Webhook
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/pricebot
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/pricebot/start_pricebot.sh
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable pricebot >/dev/null
systemctl restart pricebot
sleep 5

printf '\n7) Service status:\n'
systemctl status pricebot --no-pager -l | sed -n '1,28p' || true

printf '\n8) Local health check:\n'
HEALTH="$(curl -m 8 -sS http://127.0.0.1:8090/health || true)"
echo "$HEALTH"

if echo "$HEALTH" | grep -q '"ok"[[:space:]]*:[[:space:]]*true'; then
  printf '\n9) Save this working version as latest stable rollback archive...\n'
  tar -czf "/root/pricebot_STABLE_LOCKED_$TS.tar.gz" --exclude="pricebot/venv" -C /opt pricebot
  cp "/root/pricebot_STABLE_LOCKED_$TS.tar.gz" "/root/pricebot_STABLE_LOCKED_LATEST.tar.gz"
  ls -lh /root/pricebot_STABLE_LOCKED_LATEST.tar.gz
else
  echo "WARNING: Health check did not return ok=true. Check logs below."
  journalctl -u pricebot -n 80 --no-pager || true
  exit 1
fi

printf '\n=== DONE ===\n'
printf 'Admin: https://46.101.148.246.sslip.io/admin?key=PriceBotAdmin2026\n'
printf 'Health: https://46.101.148.246.sslip.io/health\n'
printf 'Products, database, WhatsApp tokens, and existing OpenRouter key were preserved.\n'
printf 'Next: test WhatsApp image/text replies. If OpenRouter key is missing, run /opt/pricebot/SET_OPENROUTER_KEY.sh.\n'
