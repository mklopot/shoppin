#!/bin/sh
set -e

# ==============================================================================
# Shoppin Production Container Entrypoint
# ==============================================================================

echo "==> Shoppin production entrypoint starting..."

# If DATABASE_URL is set and points to Postgres, optionally wait for database readiness
if [ -n "$DATABASE_URL" ]; then
    echo "==> Verifying database connection..."
    python -c "
import os, sys, time
import urllib.parse
db_url = os.environ.get('DATABASE_URL', '')
if 'postgres' in db_url:
    import psycopg
    parsed = urllib.parse.urlparse(db_url)
    retries = 30
    while retries > 0:
        try:
            conn = psycopg.connect(
                dbname=parsed.path.lstrip('/'),
                user=parsed.username,
                password=parsed.password,
                host=parsed.hostname,
                port=parsed.port or 5432,
                connect_timeout=3
            )
            conn.close()
            print('==> Database connection successful.')
            break
        except Exception as e:
            retries -= 1
            print(f'==> Waiting for database... ({retries} retries left): {e}')
            time.sleep(2)
    if retries == 0:
        print('==> ERROR: Could not connect to database after 30 attempts.')
        sys.exit(1)
"
fi

# Run Django database migrations
echo "==> Running database migrations..."
python manage.py migrate --noinput

# Collect static assets into staticfiles directory
echo "==> Collecting static files..."
python manage.py collectstatic --noinput

echo "==> Launching ASGI application via Daphne..."
exec "$@"
