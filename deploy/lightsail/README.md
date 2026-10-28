# Shoppin on AWS Lightsail ($5.00/month Deployment)

This directory contains the production configuration to run **Shoppin** for **\$5.00/month** on an **Amazon Lightsail** instance.

It delivers:
* **Django 6 + Channels / Daphne ASGI server** with real-time WebSockets.
* **SQLite 3 in Write-Ahead Logging (WAL) mode** (zero extra RAM, concurrent reads/writes).
* **In-Memory Channel Layer** (sub-millisecond WebSocket updates in Daphne memory).
* **Caddy Web Server** with **automatic Let's Encrypt SSL/TLS certificates** and auto-renewal.
* **Automated Daily SQLite Online Backups** with 7-day local retention and optional S3 sync.
* **Memory footprint:** Uses only **~240 MB out of 1,000 MB RAM** on the \$5 plan!

---

## 5-Minute Setup Guide

### Step 1: Create Your Lightsail Instance
1. Log in to the [AWS Lightsail Console](https://lightsail.aws.amazon.com/).
2. Click **Create instance**.
3. Select **Linux/Unix** &rarr; **OS Only** &rarr; **Ubuntu 24.04 LTS**.
4. Choose the **\$5.00 USD/month** plan (1 GB RAM, 1 vCPU, 40 GB SSD, 2 TB Transfer).
5. Give the instance a name (e.g. `shoppin-app`) and click **Create instance**.

### Step 2: Attach Free Static IP & Open Firewall Ports
1. Go to the **Networking** tab in the Lightsail Console.
2. Click **Create static IP**, attach it to your instance, and copy the IP address.
3. On the instance's **Networking** page, under **IPv4 Firewall**, ensure both **HTTP (Port 80)** and **HTTPS (Port 443)** are allowed.
4. In your domain registrar (e.g. Route 53, Cloudflare, Namecheap), add an **A-record** pointing your domain (e.g. `shoppin.yourdomain.com`) to this Static IP.

---

### Step 3: Run the Bootstrap Script
Open the browser-based SSH terminal from the Lightsail console and run:

```bash
# Clone the Shoppin repository to /app
sudo git clone https://github.com/mklopot/shoppin.git /app
cd /app

# Run the automated setup script
sudo bash deploy/lightsail/setup-lightsail.sh
```

---

### Step 4: Configure Your Domain & Secrets
```bash
# Copy the environment template
cp deploy/lightsail/.env.lightsail.example /app/.env

# Edit the environment file
nano /app/.env
```
Fill in:
* `DOMAIN_NAME=shoppin.yourdomain.com`
* `DJANGO_SECRET_KEY=...` (generate 50 random characters)
* `ALLOWED_HOSTS=shoppin.yourdomain.com,localhost,127.0.0.1`
* `CSRF_TRUSTED_ORIGINS=https://shoppin.yourdomain.com`
* `KROGER_CLIENT_ID` and `KROGER_CLIENT_SECRET` (from developer.kroger.com)

Save and exit (`Ctrl+O`, `Enter`, `Ctrl+X`).

---

### Step 5: Start the Application & Verify SSL
```bash
# Run initial migrations & static collection
sudo bash deploy/lightsail/update.sh

# Restart services
sudo systemctl restart shoppin
sudo systemctl restart caddy
```

Now open `https://shoppin.yourdomain.com` in your browser!
* Caddy has already automatically negotiated and applied your free **Let's Encrypt SSL certificate**.
* WebSockets connect at `wss://shoppin.yourdomain.com/ws/shopping/`.

---

## Operations & Maintenance

### How to Update Code After Git Push
Whenever you push new code to `v2-django`:
```bash
bash /app/deploy/lightsail/update.sh
```
This automatically pulls the latest commit, runs migrations, collects static assets, and restarts Daphne with zero downtime.

### Viewing Application Logs
```bash
# View real-time Daphne application logs
sudo journalctl -u shoppin -f

# View Caddy web server & SSL logs
sudo journalctl -u caddy -f
```

### Checking & Verifying S3 Backups
Backups run automatically every night at 03:00 UTC and save to `/app/backups/`, then stream to Amazon S3.

To test your S3 backup immediately and verify the uploaded file in AWS:
```bash
sudo bash /app/deploy/lightsail/test-s3-backup.sh
```

---

## Loading Data into Production

You have two easy ways to populate production data:

### Method 1: Clone Your Development Database via S3 (Fastest & Recommended)
This transfers all users, recipes, store locations (King Soopers, Safeway), and learned store aisles from your local dev machine in 10 seconds:

1. **On your dev machine (PowerShell):**
   ```powershell
   aws s3 cp db.sqlite3 s3://your-backup-bucket/initial_seed/db.sqlite3
   aws s3 sync media/ s3://your-backup-bucket/initial_seed/media/
   ```
2. **On Lightsail:**
   ```bash
   sudo bash /app/deploy/lightsail/load-data.sh --from-s3
   ```

### Method 2: Import Fresh from Legacy YAML Files
If you want to re-import directly from `legacy/recipe-database.yaml` and `legacy/lists/*.yaml`:
```bash
sudo bash /app/deploy/lightsail/load-data.sh --from-legacy
```

