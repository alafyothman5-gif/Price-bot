#!/usr/bin/env bash
set -Eeuo pipefail
APP_DIR="/opt/pricebot"
BACKUP_ROOT="/root/pricebot_backups"

if [[ "${PWD}" != "$APP_DIR" ]]; then
  echo "ERROR: شغّل السكربت من $APP_DIR فقط." >&2
  exit 1
fi
if [[ -d "/opt/medmcq" ]]; then
  echo "INFO: MedMCQ موجود ومحمي. لن يتم لمسه."
fi

mapfile -t BACKUPS < <(find "$BACKUP_ROOT" -maxdepth 1 -type d -name 'pricebot_backup_*' 2>/dev/null | sort -r)
if [[ ${#BACKUPS[@]} -eq 0 ]]; then
  echo "ERROR: لا توجد backups داخل $BACKUP_ROOT" >&2
  exit 1
fi

echo "آخر النسخ الاحتياطية:"
for i in "${!BACKUPS[@]}"; do
  printf '%s) %s\n' "$((i+1))" "${BACKUPS[$i]}"
  [[ $i -ge 9 ]] && break
done

CHOICE="${1:-1}"
if ! [[ "$CHOICE" =~ ^[0-9]+$ ]] || [[ "$CHOICE" -lt 1 ]] || [[ "$CHOICE" -gt "${#BACKUPS[@]}" ]]; then
  echo "ERROR: اختيار غير صحيح. مثال: ./rollback_pricebot.sh 1" >&2
  exit 1
fi
SRC="${BACKUPS[$((CHOICE-1))]}"
[[ -f "$SRC/code.tar.gz" ]] || { echo "ERROR: code.tar.gz غير موجود في $SRC" >&2; exit 1; }

echo "سيتم إرجاع ملفات الكود فقط من: $SRC"
tar -xzf "$SRC/code.tar.gz" -C "$APP_DIR"

if [[ "${RESTORE_ENV:-false}" == "true" && -f "$SRC/.env" ]]; then
  cp -a "$SRC/.env" "$APP_DIR/.env"
  echo "RESTORED_ENV=1"
else
  echo "RESTORED_ENV=0 حافظنا على .env الحالي"
fi

if [[ "${RESTORE_DB:-false}" == "true" && -f "$SRC/pricebot.db" ]]; then
  cp -a "$SRC/pricebot.db" "$APP_DIR/pricebot.db"
  echo "RESTORED_DB=1"
else
  echo "RESTORED_DB=0 حافظنا على pricebot.db الحالي"
fi

systemctl restart pricebot.service
systemctl status pricebot.service --no-pager -l || true
echo "PRICEBOT_ROLLBACK_OK"
