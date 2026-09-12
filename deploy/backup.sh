#!/usr/bin/env bash
# Nightly database backup with retention and a size sanity check.
#
#   sudo crontab -e
#   0 2 * * * DATABASE_URL=postgres://... /srv/cableerp/deploy/backup.sh >> /var/log/cableerp-backup.log 2>&1
#
# Restore drill — do this monthly, on a scratch database, or you don't have backups:
#   createdb cableerp_restore_test
#   gunzip -c /var/backups/cableerp/cableerp-YYYYmmdd-HHMMSS.sql.gz | psql cableerp_restore_test
#   psql cableerp_restore_test -c 'select count(*) from quotes_quote;'
set -euo pipefail

: "${DATABASE_URL:?Set DATABASE_URL to the database to back up}"
DEST="${BACKUP_DIR:-/var/backups/cableerp}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"

mkdir -p "$DEST"
file="$DEST/cableerp-$(date +%Y%m%d-%H%M%S).sql.gz"

pg_dump --no-owner --no-privileges "$DATABASE_URL" | gzip > "$file"
gzip -t "$file"                       # the archive must at least be readable

size=$(stat -c%s "$file")
if [ "$size" -lt 1000 ]; then
    echo "$(date -Is) backup looks empty ($size bytes): $file" >&2
    exit 1
fi

find "$DEST" -name 'cableerp-*.sql.gz' -mtime "+$KEEP_DAYS" -delete
echo "$(date -Is) wrote $file ($size bytes); kept $KEEP_DAYS days"
