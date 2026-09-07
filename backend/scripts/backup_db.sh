#!/usr/bin/env bash
# Daily DB backup. cron example (02:30):  30 2 * * * /opt/order-status-bot/backend/scripts/backup_db.sh
set -euo pipefail
OUT_DIR="${OUT_DIR:-/var/backups/order-status-bot}"
HOST="${MYSQL_HOST:-localhost}"; USER="${MYSQL_USER:-root}"; PASS="${MYSQL_PASSWORD:-root}"; DB="${MYSQL_DB:-order_bot}"
KEEP_DAYS="${KEEP_DAYS:-14}"
mkdir -p "$OUT_DIR"
FILE="$OUT_DIR/order_bot-$(date +%Y%m%d-%H%M%S).sql.gz"
mysqldump -h "$HOST" -u "$USER" -p"$PASS" --single-transaction --routines "$DB" | gzip > "$FILE"
find "$OUT_DIR" -name 'order_bot-*.sql.gz' -mtime +"$KEEP_DAYS" -delete
echo "backup written: $FILE"
