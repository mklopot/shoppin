#!/bin/bash
# ==============================================================================
# Shoppin $5/month Lightsail Bootstrap & Setup Script (Ubuntu 24.04 LTS)
# Installs Python 3.12, Caddy with automatic Let's Encrypt SSL, Daphne systemd service,
# and daily SQLite online backup cron.
# Run with sudo: sudo bash /app/deploy/lightsail/setup-lightsail.sh
# ==============================================================================

set -euo pipefail

echo "======================================================================"
echo " Starting Shoppin Lightsail Provisioning"
echo "======================================================================"

# 1. Update system packages
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get upgrade -y
apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    git \
    sqlite3 \
    python3 \
    python3-venv \
    python3-pip \
    unzip \
    cron

# Configure 1GB swapfile to provide memory headroom
if [ ! -f /swapfile ]; then
    echo "==> Configuring 1GB swapfile..."
    fallocate -l 1G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=1024
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# 2. Install official AWS CLI v2 (for S3 database backups)
if ! command -v aws &> /dev/null; then
    echo "==> Installing AWS CLI v2 for S3 backups..."
    ARCH=$(uname -m)
    if [ "$ARCH" = "aarch64" ]; then
        curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip" -o "awscliv2.zip"
    else
        curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
    fi
    unzip -q awscliv2.zip
    ./aws/install
    rm -rf aws awscliv2.zip
fi

# 3. Install official Caddy Web Server (if not already installed)
if ! command -v caddy &> /dev/null; then
    echo "==> Installing Caddy Web Server..."
    apt-get install -y debian-keyring debian-archive-keyring apt-transport-https
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -y
    apt-get install -y caddy
fi

# 3. Create and set permissions on /app
mkdir -p /app/staticfiles /app/media /app/backups
chown -R ubuntu:ubuntu /app

# 4. Create Python Virtual Environment
if [ ! -d "/app/.venv" ]; then
    echo "==> Creating Python virtualenv at /app/.venv..."
    su - ubuntu -c "python3 -m venv /app/.venv"
fi

echo "==> Installing Python dependencies..."
su - ubuntu -c "/app/.venv/bin/pip install --upgrade pip"
su - ubuntu -c "/app/.venv/bin/pip install -e /app"

# 5. Install systemd service for Daphne
echo "==> Configuring systemd service for Daphne..."
cp /app/deploy/lightsail/shoppin.service /etc/systemd/system/shoppin.service
chmod 644 /etc/systemd/system/shoppin.service
systemctl daemon-reload
systemctl enable shoppin.service

# 6. Configure Caddy web server
echo "==> Configuring Caddyfile and permissions..."
chmod 755 /app /app/staticfiles /app/media
cp /app/deploy/lightsail/Caddyfile /etc/caddy/Caddyfile
systemctl enable caddy

# 7. Configure SQLite Daily Backup Cron
echo "==> Configuring SQLite backup cron job..."
cat << 'EOF' > /etc/cron.d/shoppin-backup
0 3 * * * ubuntu /bin/bash /app/deploy/lightsail/backup-sqlite.sh >> /var/log/shoppin-backup.log 2>&1
EOF
chmod 0644 /etc/cron.d/shoppin-backup
chmod +x /app/deploy/lightsail/backup-sqlite.sh

echo "======================================================================"
echo " Lightsail Setup Complete!"
echo " Next Steps:"
echo " 1. Create your production environment file:"
echo "    cp /app/deploy/lightsail/.env.lightsail.example /app/.env"
echo "    nano /app/.env  (Set your DOMAIN_NAME and DJANGO_SECRET_KEY)"
echo " 2. Run initial database migration & collect static files:"
echo "    sudo bash /app/deploy/lightsail/update.sh"
echo " 3. Restart services:"
echo "    sudo systemctl restart shoppin"
echo "    sudo systemctl restart caddy"
echo " 4. Point your domain's DNS A-Record to this Lightsail instance's Static IP."
echo "    Caddy will automatically provision your free Let's Encrypt SSL certificate!"
echo "======================================================================"
