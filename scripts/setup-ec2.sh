#!/bin/bash
# ==============================================================================
# Shoppin Single-Host EC2 / Lightsail Bootstrap Script (Ubuntu 24.04 LTS)
# Installs Docker, Docker Compose, AWS CLI, systemd auto-start, and backup cron.
# Run as root or with sudo: sudo bash scripts/setup-ec2.sh
# ==============================================================================

set -euo pipefail

echo "======================================================================"
echo " Starting Shoppin Single-Host EC2 Initialization"
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
    unzip \
    tar \
    cron

# Configure 1GB swapfile to provide memory headroom on nano/micro instances
if [ ! -f /swapfile ]; then
    echo "==> Configuring 1GB swapfile..."
    fallocate -l 1G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=1024
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# 2. Install Official Docker Engine & Docker Compose Plugin
if ! command -v docker &> /dev/null; then
    echo "==> Installing Docker Engine..."
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc

    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null

    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    systemctl enable docker
    systemctl start docker
fi

# 3. Add ubuntu user to docker group
if id -u ubuntu &>/dev/null; then
    usermod -aG docker ubuntu
fi

# 4. Install AWS CLI v2 if not already present
if ! command -v aws &> /dev/null; then
    echo "==> Installing AWS CLI v2..."
    ARCH=$(uname -m)
    if [ "$ARCH" = "aarch64" ]; then
        curl "https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip" -o "awscliv2.zip"
    else
        curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
    fi
    unzip -q awscliv2.zip
    ./aws/install
    rm -rf aws awscliv2.zip
fi

# 5. Create application directory
mkdir -p /app
chmod 755 /app

# 6. Configure systemd unit for automatic startup on boot
cat << 'EOF' > /etc/systemd/system/shoppin.service
[Unit]
Description=Shoppin Docker Compose Application
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/app
ExecStart=/usr/bin/docker compose -f /app/docker-compose.prod.yml up -d --remove-orphans
ExecStop=/usr/bin/docker compose -f /app/docker-compose.prod.yml down
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable shoppin.service

# 7. Configure nightly database backup cron job (at 03:00 UTC)
cat << 'EOF' > /etc/cron.d/shoppin-backup
0 3 * * * root /bin/bash /app/scripts/backup-db.sh >> /var/log/shoppin-backup.log 2>&1
EOF
chmod 0644 /etc/cron.d/shoppin-backup

echo "======================================================================"
echo " Bootstrap Completed Successfully!"
echo " Next Steps:"
echo " 1. Clone your repo to /app: git clone https://github.com/mklopot/shoppin.git /app"
echo " 2. Copy .env.prod.example to .env.prod and fill in production secrets"
echo " 3. Launch the stack: cd /app && docker compose -f docker-compose.prod.yml up -d --build"
echo " 4. Point your DNS A-Record for your domain to this server's Elastic IP"
echo " 5. Caddy will automatically provision your Let's Encrypt SSL certificate!"
echo "======================================================================"
