#!/bin/bash
# ==============================================================================
# Shoppin Automated Database Backup Script
# Performs compressed pg_dump and uploads directly to Amazon S3
# Designed to run nightly via crontab on the EC2 instance
# Crontab entry: 0 3 * * * /app/scripts/backup-db.sh >> /var/log/shoppin-backup.log 2>&1
# ==============================================================================

set -eo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

if [ -f "$APP_DIR/.env.prod" ]; then
    # Export environment variables from .env.prod
    set -a
    # shellcheck disable=SC1091
    source "$APP_DIR/.env.prod"
    set +a
else
    echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] ERROR: $APP_DIR/.env.prod not found!"
    exit 1
fi

TIMESTAMP=$(date -u +"%Y%m%d_%H%M%SZ")
BACKUP_FILENAME="shoppin_db_${TIMESTAMP}.sql.gz"
S3_DEST="s3://${S3_BACKUP_BUCKET}/db_backups/${BACKUP_FILENAME}"

echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Starting database backup..."

# Dump PostgreSQL database via Docker container, compress with gzip, and stream to S3
docker compose -f "$APP_DIR/docker-compose.prod.yml" exec -T db \
    pg_dump -U "${POSTGRES_USER:-shoppin_user}" "${POSTGRES_DB:-shoppin_db}" | \
    gzip | \
    aws s3 cp - "$S3_DEST" --sse AES256

if [ $? -eq 0 ]; then
    echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] SUCCESS: Database backup uploaded to ${S3_DEST}"
else
    echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] ERROR: Database backup to S3 failed!"
    exit 1
fi
