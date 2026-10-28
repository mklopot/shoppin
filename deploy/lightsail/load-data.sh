#!/bin/bash
# ==============================================================================
# Shoppin Data Import Helper for Production (Lightsail)
# Imports data from:
#   1. Legacy YAML files (recipes & preset lists)
#   2. Local dev instance via S3 snapshot (cloning entire dev database)
#   3. Django JSON fixture file
#
# Usage:
#   sudo bash deploy/lightsail/load-data.sh --from-legacy
#   sudo bash deploy/lightsail/load-data.sh --from-s3
#   sudo bash deploy/lightsail/load-data.sh --from-fixture /path/to/fixture.json
# ==============================================================================

set -eo pipefail

APP_DIR="/app"
VENV_PYTHON="$APP_DIR/.venv/bin/python"

if [ ! -f "$VENV_PYTHON" ]; then
    echo "ERROR: Virtual environment not found at $APP_DIR/.venv!"
    echo "Run 'sudo bash $APP_DIR/deploy/lightsail/setup-lightsail.sh' first."
    exit 1
fi

MODE="${1:-}"

case "$MODE" in
    --from-legacy)
        echo "======================================================================"
        echo " Importing Data from Legacy YAML Files (/app/legacy/)"
        echo "======================================================================"
        cd "$APP_DIR"
        "$VENV_PYTHON" "$APP_DIR/manage.py" migrate --noinput
        "$VENV_PYTHON" "$APP_DIR/manage.py" import_legacy_data --overwrite
        echo "==> Legacy data imported successfully!"
        sudo systemctl restart shoppin
        ;;

    --from-s3)
        echo "======================================================================"
        echo " Downloading Development Database from Amazon S3"
        echo "======================================================================"
        if [ ! -f "$APP_DIR/.env" ]; then
            echo "ERROR: /app/.env does not exist!"
            exit 1
        fi
        S3_BUCKET=$(grep -E '^S3_BACKUP_BUCKET=' "$APP_DIR/.env" | cut -d '=' -f2- | tr -d '"' | tr -d "'" || true)
        AWS_KEY=$(grep -E '^AWS_ACCESS_KEY_ID=' "$APP_DIR/.env" | cut -d '=' -f2- | tr -d '"' | tr -d "'" || true)
        AWS_SECRET=$(grep -E '^AWS_SECRET_ACCESS_KEY=' "$APP_DIR/.env" | cut -d '=' -f2- | tr -d '"' | tr -d "'" || true)
        AWS_REG=$(grep -E '^AWS_DEFAULT_REGION=' "$APP_DIR/.env" | cut -d '=' -f2- | tr -d '"' | tr -d "'" || true)

        if [ -n "$AWS_KEY" ]; then export AWS_ACCESS_KEY_ID="$AWS_KEY"; fi
        if [ -n "$AWS_SECRET" ]; then export AWS_SECRET_ACCESS_KEY="$AWS_SECRET"; fi
        if [ -n "$AWS_REG" ]; then export AWS_DEFAULT_REGION="$AWS_REG"; fi

        if [ -z "$S3_BUCKET" ]; then
            echo "ERROR: S3_BACKUP_BUCKET is not set in /app/.env!"
            exit 1
        fi

        echo "==> Stopping Daphne service during database restore..."
        sudo systemctl stop shoppin || true

        echo "==> Downloading s3://${S3_BUCKET}/initial_seed/db.sqlite3..."
        aws s3 cp "s3://${S3_BUCKET}/initial_seed/db.sqlite3" "$APP_DIR/db.sqlite3"
        chown ubuntu:ubuntu "$APP_DIR/db.sqlite3"

        echo "==> Syncing media uploads from S3 (recipe images)..."
        aws s3 sync "s3://${S3_BUCKET}/initial_seed/media/" "$APP_DIR/media/" || true
        chown -R ubuntu:ubuntu "$APP_DIR/media"

        echo "==> Applying any pending schema migrations..."
        "$VENV_PYTHON" "$APP_DIR/manage.py" migrate --noinput

        echo "==> Restarting Daphne service..."
        sudo systemctl start shoppin
        echo "==> SUCCESS: Development database and media restored to production!"
        ;;

    --from-fixture)
        FIXTURE_PATH="${2:-}"
        if [ -z "$FIXTURE_PATH" ] || [ ! -f "$FIXTURE_PATH" ]; then
            echo "ERROR: Please specify a valid fixture file path: --from-fixture /path/to/data.json"
            exit 1
        fi
        echo "======================================================================"
        echo " Loading Django Fixture: $FIXTURE_PATH"
        echo "======================================================================"
        cd "$APP_DIR"
        "$VENV_PYTHON" "$APP_DIR/manage.py" migrate --noinput
        "$VENV_PYTHON" "$APP_DIR/manage.py" loaddata "$FIXTURE_PATH"
        echo "==> Fixture loaded successfully!"
        sudo systemctl restart shoppin
        ;;

    *)
        echo "======================================================================"
        echo " Shoppin Data Loader Options:"
        echo "======================================================================"
        echo " Option 1: Import directly from legacy YAML files:"
        echo "   sudo bash deploy/lightsail/load-data.sh --from-legacy"
        echo ""
        echo " Option 2: Restore full dev database snapshot from S3:"
        echo "   sudo bash deploy/lightsail/load-data.sh --from-s3"
        echo ""
        echo " Option 3: Load a Django JSON fixture:"
        echo "   sudo bash deploy/lightsail/load-data.sh --from-fixture <path-to-json>"
        echo "======================================================================"
        exit 1
        ;;
esac
