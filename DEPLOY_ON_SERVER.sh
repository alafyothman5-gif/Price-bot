#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/pricebot"
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
TS="$(date +%Y%m%d_%H%M%S)"

echo "=== PriceBot deploy started ==="
echo "Repo: $REPO_DIR"
echo "App : $APP_DIR"

if [ ! -d "$APP_DIR" ]; then
  echo "Creating $APP_DIR"
  mkdir -p "$APP_DIR"
fi

echo "Creating backup..."
tar --exclude="$APP_DIR/venv" -czf "/root/pricebot_BACKUP_BEFORE_DEPLOY_$TS.tar.gz" -C /opt pricebot 2>/dev/null || true
ls -lh "/root/pricebot_BACKUP_BEFORE_DEPLOY_$TS.tar.gz" 2>/dev/null || true

for f in app.py requirements.txt README_START_HERE.md products_template.csv .env.example .gitignore; do
  if [ -f "$REPO_DIR/$f" ]; then
    cp "$REPO_DIR/$f" "$APP_DIR/$f"
  fi
done

if [ ! -f "$APP_DIR/.env" ]; then
  echo "WARNING: $APP_DIR/.env not found. Creating from .env.example. You must edit it with real token before WhatsApp sends replies."
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
fi

if [ ! -f "$APP_DIR/products.csv" ]; then
  cp "$APP_DIR/products_template.csv" "$APP_DIR/products.csv"
fi

if [ ! -f "$APP_DIR/orders.csv" ]; then
  printf '\ufefftime,phone,product,price,available,notes,message,status\n' > "$APP_DIR/orders.csv"
fi

cd "$APP_DIR"

if [ ! -d venv ]; then
  python3 -m venv venv
fi

./venv/bin/python -m pip install --upgrade pip
./venv/bin/pip install -r requirements.txt
./venv/bin/python -m py_compile app.py

cat > /etc/systemd/system/pricebot.service <<'SERVICE'
[Unit]
Description=PriceBot WhatsApp Webhook
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/pricebot
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/pricebot/venv/bin/python /opt/pricebot/app.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable pricebot
systemctl restart pricebot
sleep 2

# Daily WhatsApp report to admin at 21:00 server time.
cat > /usr/local/bin/pricebot_daily_report.sh <<'REPORT'
#!/usr/bin/env bash
set -e
APP_DIR="/opt/pricebot"
ENV_FILE="$APP_DIR/.env"
ADMIN_KEY="PriceBotAdmin2026"
if [ -f "$ENV_FILE" ]; then
  found="$(grep -E '^ADMIN_KEY=' "$ENV_FILE" | tail -1 | cut -d= -f2- || true)"
  if [ -n "$found" ]; then ADMIN_KEY="$found"; fi
fi
for PORT in 8095 8090 8080; do
  if curl -fsS "http://127.0.0.1:${PORT}/admin/daily-report/send?key=${ADMIN_KEY}&auto=1" >/dev/null 2>&1; then
    exit 0
  fi
done
exit 0
REPORT
chmod +x /usr/local/bin/pricebot_daily_report.sh
cat > /etc/cron.d/pricebot_daily_report <<'CRON'
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
0 21 * * * root /usr/local/bin/pricebot_daily_report.sh >/tmp/pricebot_daily_report.log 2>&1
CRON

systemctl --no-pager --full status pricebot | sed -n '1,14p'

echo "=== PriceBot deploy finished ==="
echo "Admin: /admin?key=PriceBotAdmin2026"
echo "Orders: /admin/orders?key=PriceBotAdmin2026"
echo "Analytics: /admin/analytics?key=PriceBotAdmin2026"
