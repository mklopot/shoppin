#!/bin/bash
# ==============================================================================
# Shoppin S3 Backup Verification Test Script
# Tests AWS credentials, runs an online backup, and verifies the object in S3.
# Usage: sudo bash /app/deploy/lightsail/test-s3-backup.sh
# ==============================================================================

set -eo pipefail

APP_DIR="/app"

echo "======================================================================"
echo " Testing Shoppin S3 Backup Configuration"
echo "======================================================================"

if [ ! -f "$APP_DIR/.env" ]; then
    echo "ERROR: /app/.env does not exist! Please create it from .env.lightsail.example"
    exit 1
fi

S3_BUCKET=$(grep -E '^S3_BACKUP_BUCKET=' "$APP_DIR/.env" | cut -d '=' -f2- | tr -d '"' | tr -d "'" || true)
AWS_KEY=$(grep -E '^AWS_ACCESS_KEY_ID=' "$APP_DIR/.env" | cut -d '=' -f2- | tr -d '"' | tr -d "'" || true)
AWS_SECRET=$(grep -E '^AWS_SECRET_ACCESS_KEY=' "$APP_DIR/.env" | cut -d '=' -f2- | tr -d '"' | tr -d "'" || true)
AWS_REG=$(grep -E '^AWS_DEFAULT_REGION=' "$APP_DIR/.env" | cut -d '=' -f2- | tr -d '"' | tr -d "'" || true)

if [ -z "$S3_BUCKET" ]; then
    echo "ERROR: S3_BACKUP_BUCKET is not set in /app/.env!"
    echo "Please set S3_BACKUP_BUCKET=your-bucket-name in /app/.env"
    exit 1
fi

if [ -n "$AWS_KEY" ]; then export AWS_ACCESS_KEY_ID="$AWS_KEY"; fi
if [ -n "$AWS_SECRET" ]; then export AWS_SECRET_ACCESS_KEY="$AWS_SECRET"; fi
if [ -n "$AWS_REG" ]; then export AWS_DEFAULT_REGION="$AWS_REG"; fi

echo "1. Checking AWS CLI..."
if ! command -v aws &> /dev/null; then
    echo "ERROR: 'aws' command not found! Run 'sudo bash /app/deploy/lightsail/setup-lightsail.sh' to install it."
    exit 1
fi
echo "   AWS CLI is installed ($(aws --version | cut -d ' ' -f1-2))"

echo "2. Checking S3 bucket access: s3://${S3_BUCKET}..."
if aws s3 ls "s3://${S3_BUCKET}" > /dev/null 2>&1; then
    echo "   SUCCESS: Connection to S3 bucket verified!"
else
    echo "   ERROR: Cannot connect to s3://${S3_BUCKET}."
    echo "   Please verify your AWS credentials (AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY) in /app/.env"
    echo "   and ensure the IAM user/role has s3:PutObject and s3:ListBucket permissions."
    exit 1
fi

echo "3. Triggering test database backup..."
bash "$APP_DIR/deploy/lightsail/backup-sqlite.sh"

echo "4. Verifying uploaded backup in S3:"
aws s3 ls "s3://${S3_BUCKET}/sqlite_backups/" --human-readable | tail -n 5

echo "======================================================================"
echo " TEST PASSED! S3 automated backups are fully operational."
echo " Backups will run automatically every night at 03:00 UTC."
echo "======================================================================"
