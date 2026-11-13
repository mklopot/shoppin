#!/bin/bash
# ==============================================================================
# Shoppin SQLite Safe Online Backup Script
# Performs a non-blocking, corruption-free online backup of db.sqlite3,
# compresses it, keeps 7 local copies, and optionally uploads to Amazon S3.
#
# Crontab schedule (daily at 03:00 UTC):
# 0 3 * * * ubuntu /bin/bash /app/deploy/lightsail/backup-sqlite.sh >> /var/log/shoppin-backup.log 2>&1
# ==============================================================================

set -eo pipefail

APP_DIR="/app"
DB_FILE="$APP_DIR/db.sqlite3"
BACKUP_DIR="$APP_DIR/backups"
TIMESTAMP=$(date -u +"%Y%m%d_%H%M%SZ")
TEMP_BACKUP="/tmp/shoppin_raw_${TIMESTAMP}.db"
FINAL_BACKUP="$BACKUP_DIR/shoppin_db_${TIMESTAMP}.db.gz"

mkdir -p "$BACKUP_DIR"

if [ ! -f "$DB_FILE" ]; then
    echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] ERROR: $DB_FILE does not exist!"
    exit 1
fi

echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Starting online SQLite backup..."

# 1. Non-blocking SQLite online backup API
sqlite3 "$DB_FILE" ".backup '$TEMP_BACKUP'"

# 2. Compress the backup copy
gzip -c "$TEMP_BACKUP" > "$FINAL_BACKUP"
rm -f "$TEMP_BACKUP"

echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Local backup saved: $FINAL_BACKUP ($(du -h "$FINAL_BACKUP" | cut -f1))"

# 3. Rotate local backups: Keep last 7 backups, delete older ones
find "$BACKUP_DIR" -type f -name "shoppin_db_*.db.gz" -mtime +7 -delete

# 4. Push to Amazon S3 if S3_BACKUP_BUCKET is configured in .env
if [ -f "$APP_DIR/.env" ]; then
    S3_BUCKET=$(grep -E '^S3_BACKUP_BUCKET=' "$APP_DIR/.env" | cut -d '=' -f2- | tr -d '"' | tr -d "'" || true)
    AWS_KEY=$(grep -E '^AWS_ACCESS_KEY_ID=' "$APP_DIR/.env" | cut -d '=' -f2- | tr -d '"' | tr -d "'" || true)
    AWS_SECRET=$(grep -E '^AWS_SECRET_ACCESS_KEY=' "$APP_DIR/.env" | cut -d '=' -f2- | tr -d '"' | tr -d "'" || true)
    AWS_REG=$(grep -E '^AWS_DEFAULT_REGION=' "$APP_DIR/.env" | cut -d '=' -f2- | tr -d '"' | tr -d "'" || true)

    if [ -n "$AWS_KEY" ]; then export AWS_ACCESS_KEY_ID="$AWS_KEY"; fi
    if [ -n "$AWS_SECRET" ]; then export AWS_SECRET_ACCESS_KEY="$AWS_SECRET"; fi
    if [ -n "$AWS_REG" ]; then export AWS_DEFAULT_REGION="$AWS_REG"; fi

    if [ -n "$S3_BUCKET" ]; then
        if ! command -v aws &> /dev/null; then
            echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] ERROR: S3_BACKUP_BUCKET is configured, but the 'aws' CLI is not installed!"
            exit 1
        fi
        echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Uploading to Amazon S3: s3://${S3_BUCKET}/sqlite_backups/..."
        aws s3 cp "$FINAL_BACKUP" "s3://${S3_BUCKET}/sqlite_backups/$(basename "$FINAL_BACKUP")" --sse AES256
        echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] S3 upload complete: s3://${S3_BUCKET}/sqlite_backups/$(basename "$FINAL_BACKUP")"
    else
        echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] NOTE: S3_BACKUP_BUCKET is not set in $APP_DIR/.env. Backup was saved locally only."
    fi
fi

echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Backup process completed successfully."
