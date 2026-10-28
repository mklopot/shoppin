#!/bin/bash
# ==============================================================================
# Shoppin Zero-Downtime Update Script for Lightsail
# Pulls git updates, applies migrations, collects static assets, and restarts Daphne.
# Usage: bash /app/deploy/lightsail/update.sh
# ==============================================================================

set -euo pipefail

APP_DIR="/app"
cd "$APP_DIR"

echo "==> Pulling latest code from git..."
git pull origin v2-django

echo "==> Updating Python dependencies..."
"$APP_DIR/.venv/bin/pip" install -q -e "$APP_DIR"

echo "==> Applying database migrations..."
"$APP_DIR/.venv/bin/python" "$APP_DIR/manage.py" migrate --noinput

echo "==> Collecting static assets..."
"$APP_DIR/.venv/bin/python" "$APP_DIR/manage.py" collectstatic --noinput

echo "==> Restarting Shoppin Daphne service..."
sudo systemctl restart shoppin

echo "==> Setting directory permissions..."
sudo chmod 755 "$APP_DIR" "$APP_DIR/staticfiles" "$APP_DIR/media"

echo "==> Configuring and restarting Caddy web server..."
sudo cp "$APP_DIR/deploy/lightsail/Caddyfile" /etc/caddy/Caddyfile
if [ -f "$APP_DIR/.env" ]; then
    DOMAIN=$(grep -E '^DOMAIN_NAME=' "$APP_DIR/.env" | cut -d '=' -f2- | tr -d '"' | tr -d "'" | tr -d ' ' || true)
    if [ -n "$DOMAIN" ] && [ "$DOMAIN" != "localhost" ]; then
        echo "==> Configuring Caddy for domain: $DOMAIN"
        sudo sed -i "s/{\$DOMAIN_NAME:localhost}/$DOMAIN/g" /etc/caddy/Caddyfile
    fi
fi
sudo systemctl restart caddy

echo "==> Verifying application health..."
sleep 2
if curl -fsSL http://127.0.0.1:8000/health/ > /dev/null; then
    echo "==> SUCCESS: Application is healthy and serving requests!"
else
    echo "==> WARNING: Health check failed or timed out. Check journalctl -u shoppin -n 50"
    exit 1
fi
