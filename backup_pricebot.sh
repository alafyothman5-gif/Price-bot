#!/usr/bin/env bash
set -Eeuo pipefail
APP_DIR="/opt/pricebot"
BACKUP_ROOT="/root/pricebot_backups"
STAMP="$(date +%Y%m%d_%H%M%S)"
DEST="$BACKUP_ROOT/pricebot_backup_$STAMP"

if [[ "${PWD}" != "$APP_DIR" ]]; then
  echo "ERROR: شغّل السكربت من $APP_DIR فقط." >&2
  exit 1
fi
if [[ -d "/opt/medmcq" ]]; then
  echo "INFO: MedMCQ موجود ومحمي. لن يتم لمسه."
fi
mkdir -p "$DEST"

tar --exclude='./venv' --exclude='./.venv' --exclude='./backups' --exclude='./.git' --exclude='./__pycache__' \
    --exclude='./pricebot.db' --exclude='./.env' \
    -czf "$DEST/code.tar.gz" -C "$APP_DIR" .

[[ -f "$APP_DIR/pricebot.db" ]] && cp -a "$APP_DIR/pricebot.db" "$DEST/pricebot.db"
[[ -f "$APP_DIR/.env" ]] && cp -a "$APP_DIR/.env" "$DEST/.env"
[[ -f "/etc/systemd/system/pricebot.service" ]] && cp -a "/etc/systemd/system/pricebot.service" "$DEST/pricebot.service"

echo "PRICEBOT_BACKUP_OK: $DEST"
