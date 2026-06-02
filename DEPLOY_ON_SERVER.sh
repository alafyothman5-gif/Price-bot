#!/usr/bin/env bash
set -e

APP="/opt/pricebot"
TS="$(date +%Y%m%d_%H%M%S)"
BACKUP="/opt/pricebot_BACKUP_BEFORE_SINGLE_FILE_${TS}"
PRESERVE="/root/pricebot_preserve_single_file_${TS}"

echo "1) حفظ الملفات المهمة..."
mkdir -p "$PRESERVE"
cp "$APP/.env" "$PRESERVE/.env" 2>/dev/null || true
cp "$APP/pricebot.db" "$PRESERVE/pricebot.db" 2>/dev/null || true
cp "$APP/pricebot.db-wal" "$PRESERVE/pricebot.db-wal" 2>/dev/null || true
cp "$APP/pricebot.db-shm" "$PRESERVE/pricebot.db-shm" 2>/dev/null || true
cp -r "$APP/uploads" "$PRESERVE/uploads" 2>/dev/null || true
cp -r "$APP/media" "$PRESERVE/media" 2>/dev/null || true
cp -r "$APP/images" "$PRESERVE/images" 2>/dev/null || true

echo "2) حفظ نسخة قديمة..."
mkdir -p "$BACKUP"
shopt -s dotglob nullglob
cp -a "$APP"/* "$BACKUP"/ 2>/dev/null || true

echo "3) إرجاع الملفات المهمة..."
mkdir -p "$APP/uploads" "$APP/media" "$APP/images"
cp "$PRESERVE/.env" "$APP/.env" 2>/dev/null || true
cp "$PRESERVE/pricebot.db" "$APP/pricebot.db" 2>/dev/null || true
cp "$PRESERVE/pricebot.db-wal" "$APP/pricebot.db-wal" 2>/dev/null || true
cp "$PRESERVE/pricebot.db-shm" "$APP/pricebot.db-shm" 2>/dev/null || true
cp -r "$PRESERVE/uploads" "$APP/uploads" 2>/dev/null || true
cp -r "$PRESERVE/media" "$APP/media" 2>/dev/null || true
cp -r "$PRESERVE/images" "$APP/images" 2>/dev/null || true

echo "4) تثبيت المتطلبات..."
cd "$APP"
python3 -m venv venv
./venv/bin/pip install --upgrade pip >/dev/null
./venv/bin/pip install -r requirements.txt

echo "5) فحص الكود..."
./venv/bin/python -m py_compile app.py

echo "6) تشغيل البوت..."
systemctl daemon-reload
systemctl restart pricebot
sleep 3

echo "7) حالة الخدمة:"
systemctl --no-pager --full status pricebot | sed -n '1,12p'

echo "✅ انتهى النشر"
echo "Backup: $BACKUP"
