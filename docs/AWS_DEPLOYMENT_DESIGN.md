# Production Deployment Design: Shoppin on AWS

This document specifies the end-to-end architecture, configuration, and operational procedures for deploying the **Shoppin** application to Amazon Web Services (AWS) in a high-availability, secure, and production-ready environment.

---

## 1. High-Level Architecture

Shoppin is a real-time web application built on **Django 6**, **Channels**, and the **Daphne** ASGI server, delivering server-rendered HTML via **HTMX** and real-time state synchronization via **WebSockets** (`/ws/shopping/`).

### System Architecture Diagram

```mermaid
flowchart TD
    subgraph Client["Users & Mobile Browsers"]
        Browser["Web Browser / Mobile PWA"]
    end

    subgraph Edge["AWS Edge Services"]
        R53["Amazon Route 53 (DNS)"]
        CF["Amazon CloudFront (CDN)"]
        WAF["AWS WAF (Web Application Firewall)"]
    end

    subgraph VPC["Amazon VPC (Multi-AZ: us-east-1a, 1b, 1c)"]
        subgraph PublicSubnets["Public Subnets (Tier 1)"]
            ALB["Application Load Balancer (ALB)\nTLS 1.3 Termination"]
            NAT["NAT Gateways (Egress)"]
        end

        subgraph PrivateAppSubnets["Private Application Subnets (Tier 2)"]
            subgraph ECSCluster["ECS Fargate Cluster"]
                Task1["Daphne ASGI Task 1\n(HTTP & WS)"]
                Task2["Daphne ASGI Task 2\n(HTTP & WS)"]
                TaskN["Daphne ASGI Task N\n(Auto-Scaled)"]
            end
        end

        subgraph PrivateDataSubnets["Private Isolated Data Subnets (Tier 3)"]
            RDS["Amazon RDS PostgreSQL 16\n(Multi-AZ Standby)"]
            Redis["Amazon ElastiCache Redis\n(Channels Layer Replication Group)"]
        end
    end

    subgraph Storage["Cloud Storage & Secrets"]
        S3Media["Amazon S3\nUser Recipe Photos & Media"]
        S3Static["Amazon S3 / Build Assets\nStatic Files"]
        SM["AWS Secrets Manager\n(KMS CMK Encrypted)"]
    end

    subgraph Observability["Monitoring & Operations"]
        CW["Amazon CloudWatch Logs & Metrics"]
        SNS["Amazon SNS Alerts (Slack / Email)"]
        ECR["Amazon ECR (Container Registry)"]
    end

    Browser -->|DNS Query| R53
    Browser -->|Static Assets| CF
    CF --> S3Static
    Browser -->|HTTPS & WSS Traffic| WAF
    WAF --> ALB
    ALB -->|HTTP Requests & WebSocket Upgrades| Task1 & Task2 & TaskN

    Task1 & Task2 & TaskN -->|WebSocket Channel Layer| Redis
    Task1 & Task2 & TaskN -->|Queries via SSL| RDS
    Task1 & Task2 & TaskN -->|Upload Media| S3Media
    Task1 & Task2 & TaskN -->|Inject Secrets on Boot| SM
    Task1 & Task2 & TaskN -->|Structured JSON Logs| CW
    Task1 & Task2 & TaskN -->|Outbound Kroger API| NAT
    CW -->|Alarms| SNS
```

---

## 2. Secrets Management

### 2.1 Storage & Encryption
Secrets are stored in **AWS Secrets Manager** and encrypted at rest with an AWS Key Management Service (KMS) Customer Managed Key (CMK).

| Secret Name | Key in Secret | Purpose | Rotation Strategy |
| :--- | :--- | :--- | :--- |
| `/shoppin/prod/django` | `SECRET_KEY` | Cryptographic signing for sessions and CSRF tokens | Annual manual or on-demand |
| `/shoppin/prod/database` | `DATABASE_URL` | PostgreSQL connection URL with master password | Automated 30-day RDS Lambda rotation |
| `/shoppin/prod/redis` | `REDIS_URL` | Redis connection URL with AUTH token | Semi-annual manual rotation |
| `/shoppin/prod/kroger` | `KROGER_CLIENT_ID`<br>`KROGER_CLIENT_SECRET` | Kroger Developer API credentials for aisle queries | Managed via developer.kroger.com |
| `/shoppin/prod/google` | `GOOGLE_CLIENT_ID`<br>`GOOGLE_CLIENT_SECRET` | Google OAuth 2.0 Single Sign-On | Managed via Google Cloud Console |

### 2.2 Native Container Injection (Zero-Code Overhead)
To eliminate latency, external network dependencies at startup, and avoid bundling AWS SDKs into core Django code, secrets are resolved by the AWS ECS Agent directly from AWS Secrets Manager and passed as standard POSIX environment variables into the container memory.

```json
{
  "containerDefinitions": [
    {
      "name": "shoppin-web",
      "image": "123456789012.dkr.ecr.us-east-1.amazonaws.com/shoppin:latest",
      "environment": [
        { "name": "DJANGO_DEBUG", "value": "False" },
        { "name": "DJANGO_SETTINGS_MODULE", "value": "config.settings_prod" },
        { "name": "DEV_AUTO_LOGIN", "value": "False" },
        { "name": "ALLOWED_HOSTS", "value": "shoppin.app,api.shoppin.app" }
      ],
      "secrets": [
        {
          "name": "DJANGO_SECRET_KEY",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:123456789012:secret:/shoppin/prod/django:SECRET_KEY::"
        },
        {
          "name": "DATABASE_URL",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:123456789012:secret:/shoppin/prod/database:DATABASE_URL::"
        },
        {
          "name": "REDIS_URL",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:123456789012:secret:/shoppin/prod/redis:REDIS_URL::"
        },
        {
          "name": "KROGER_CLIENT_ID",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:123456789012:secret:/shoppin/prod/kroger:KROGER_CLIENT_ID::"
        },
        {
          "name": "KROGER_CLIENT_SECRET",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:123456789012:secret:/shoppin/prod/kroger:KROGER_CLIENT_SECRET::"
        },
        {
          "name": "GOOGLE_CLIENT_ID",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:123456789012:secret:/shoppin/prod/google:GOOGLE_CLIENT_ID::"
        },
        {
          "name": "GOOGLE_CLIENT_SECRET",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:123456789012:secret:/shoppin/prod/google:GOOGLE_CLIENT_SECRET::"
        }
      ]
    }
  ]
}
```

### 2.3 IAM Least Privilege Roles
* **`ecsTaskExecutionRole`**: Grants the ECS infrastructure agent permission to pull container images from Amazon ECR, stream logs to CloudWatch, and retrieve values from Secrets Manager and decrypt KMS keys.
* **`ecsTaskRole`**: Grants the running Django container runtime permissions (e.g. `s3:PutObject`, `s3:GetObject` on the Recipe Media Bucket). It does *not* possess Secrets Manager read access.

---

## 3. Database Management (Amazon RDS PostgreSQL)

### 3.1 Provisioning Specification
* **Engine:** PostgreSQL 16.x
* **Instance Tier:** `db.m7g.large` (2 vCPU, 8 GB RAM, Graviton3 for optimal price/performance) for production; `db.t4g.medium` for staging.
* **Storage:** 100 GB GP3 SSD (Autoscaling up to 500 GB; 3000 baseline IOPS, 125 MB/s throughput).
* **High Availability:** **Multi-AZ enabled** (Synchronous replication to a standby instance in a secondary Availability Zone with automatic failover in < 60 seconds).
* **Network Placement:** Subnet group restricted exclusively to Private Data Subnets (Tier 3), inaccessible from the public internet.

### 3.2 Connection Pooling & RDS Proxy
Because Daphne operates an asynchronous event loop handling hundreds of concurrent persistent WebSocket connections, standard direct database connections can quickly saturate PostgreSQL's `max_connections` limit.
* **AWS RDS Proxy** is placed in front of PostgreSQL.
* Pools and multiplexes database connections across all ASGI tasks.
* Enforces TLS 1.3 encryption in transit (`sslmode=require`).
* Eliminates application-level connection drops during Multi-AZ failovers by automatically redirecting queries to the promoted standby.

### 3.3 Backup, Retention & Point-in-Time Recovery
* **Automated Daily Snapshots:** Retained for 30 days.
* **Continuous Write-Ahead Log (WAL) Archival:** Retained in S3 to enable **Point-in-Time Recovery (PITR)** to any second within the retention window (Recovery Point Objective [RPO] &le; 5 minutes).
* **Pre-Deployment Snapshots:** The CI/CD pipeline triggers an automated manual snapshot before any database migration executes.

---

## 4. Data Load & Migration Strategy

### 4.1 Initial Seed & Migration from SQLite to RDS PostgreSQL
To transition from local SQLite development to production PostgreSQL:

1. **Dump Normalized Data from SQLite:**
   ```powershell
   python manage.py dumpdata --natural-foreign --natural-primary `
       -e contenttypes -e auth.Permission `
       --indent 2 > initial_data.json
   ```
2. **Provision RDS PostgreSQL & Run Migrations:**
   ```bash
   DATABASE_URL="postgres://user:pass@rds-endpoint:5432/shoppindb" python manage.py migrate
   ```
3. **Load Serialized Fixtures:**
   ```bash
   DATABASE_URL="postgres://user:pass@rds-endpoint:5432/shoppindb" python manage.py loaddata initial_data.json
   ```
4. **Synchronize PostgreSQL Primary Key Sequences:**
   PostgreSQL uses sequences for auto-incrementing primary keys. After a direct data load, reset sequence pointers to prevent constraint violations:
   ```bash
   python manage.py sqlsequencereset core recipes shopping mealplans | python manage.py dbshell
   ```

### 4.2 Zero-Downtime Deployment Migrations (Expand and Contract)
To avoid locks or application downtime during rolling deployments:
1. **Never make backward-incompatible database changes in a single step.**
   * *Phase 1 (Expand):* Add new nullable columns or tables. Deploy code that writes to both old and new columns.
   * *Phase 2 (Migrate):* Backfill existing rows via a background data migration script.
   * *Phase 3 (Contract):* Deploy code that reads only from new columns. Remove deprecated columns in a subsequent release.
2. **Execute Migrations via Isolated ECS One-Shot Tasks:**
   The CI/CD pipeline runs `manage.py migrate` as a standalone one-off ECS task *before* initiating the rolling container rollout. Web containers never execute migrations on boot, preventing multi-task race conditions.

---

## 5. CI/CD Pipeline (GitHub Actions & AWS OIDC)

### 5.1 Pipeline Flow

```mermaid
sequenceDiagram
    autonumber
    actor Dev as Developer
    participant GH as GitHub Actions
    participant ECR as Amazon ECR
    participant ECS as Amazon ECS
    participant RDS as Amazon RDS
    participant ALB as Application Load Balancer

    Dev->>GH: Push to main branch
    activate GH
    GH->>GH: Run Ruff Linter & Pytest Suite
    GH->>GH: Django check --deploy
    GH->>ECR: Build multi-stage Docker image & push (Git SHA tag)
    GH->>RDS: Create pre-deploy snapshot
    GH->>ECS: Run one-off Fargate Task: `manage.py migrate`
    ECS-->>GH: Migration Task Complete (Exit Code 0)
    GH->>ECS: Update Service (Rolling deployment: min 100%, max 200%)
    activate ECS
    ECS->>ECR: Pull new image
    ECS->>ECS: Start new Fargate tasks
    ECS->>ALB: Register new tasks in Target Group
    ALB->>ECS: Perform /health/ health check
    ALB-->>ECS: Health check passed (200 OK)
    ALB->>ECS: Drain & terminate old tasks (stopTimeout: 60s)
    deactivate ECS
    GH->>ALB: Execute end-to-end smoke tests
    GH-->>Dev: Deployment Successful
    deactivate GH
```

### 5.2 Key Pipeline Configuration (`.github/workflows/deploy.yml`)
* **Authentication:** Uses AWS **OpenID Connect (OIDC)** federated credentials. No long-lived AWS secret access keys are stored in GitHub secrets.
* **Rolling Strategy:** `minimumHealthyPercent = 100`, `maximumPercent = 200`. Ensures existing capacity remains intact until all replacement containers pass ALB health checks.
* **Graceful Termination:** ECS tasks are configured with `stopTimeout: 60`. When ECS initiates task replacement, Daphne receives `SIGTERM`, ceases accepting new connections, and allows existing WebSocket channels to drain cleanly.

---

## 6. Load Balancing & WebSocket Handling

### 6.1 Application Load Balancer (ALB) Setup
* **Internet-Facing ALB** deployed across 3 Public Subnets (`us-east-1a`, `us-east-1b`, `us-east-1c`).
* **Listeners:**
  * **Port 80 (HTTP):** Permanent 301 redirect to `https://#{host}:443/#{path}?#{query}`.
  * **Port 443 (HTTPS):** Terminates TLS 1.3 and forwards requests to the ECS Target Group on port 8000.

### 6.2 WebSocket Support & Daphne Configuration
Shoppin uses Daphne as its ASGI server. Daphne handles both HTTP and WebSocket protocols on the same port:
* **Protocol Upgrades:** When HTMX or a browser requests `wss://yourdomain.com/ws/shopping/`, the client sends `Upgrade: websocket`. The ALB natively handles WebSocket upgrades over HTTP/1.1 and HTTP/2.
* **ALB Idle Timeout:** The default ALB idle timeout is 60 seconds. For real-time shopping collaboration, the ALB idle timeout is increased to **300 seconds** (or 600 seconds) to prevent premature disconnection of idle supermarket shopping sessions.
* **Daphne Heartbeats:** Application-level WebSocket keep-alives (ping/pong every 30 seconds) maintain active connection state across mobile networks.
* **Target Group Health Check:**
  * Endpoint: `/health/`
  * Interval: 15 seconds
  * Timeout: 5 seconds
  * Healthy Threshold: 2 consecutive successes
  * Unhealthy Threshold: 3 consecutive failures

---

## 7. SSL Termination & Certificate Management

### 7.1 AWS Certificate Manager (ACM) vs. Let's Encrypt

| Criterion | AWS Certificate Manager (ACM) *(Recommended)* | Let's Encrypt on AWS |
| :--- | :--- | :--- |
| **Cost** | 100% Free | 100% Free |
| **Validation Mechanism** | Route 53 DNS record (automated) | HTTP-01 or DNS-01 ACME challenge |
| **Renewal Maintenance** | **Zero.** AWS auto-renews 60 days prior | Requires cron script, Certbot Lambda, or proxy |
| **ALB Integration** | Direct native binding to ALB listener | Must be imported via API or terminated on EC2 |
| **Failure Risk** | Near zero | Renewal script failure, rate limits, API drift |

> [!TIP]
> **Production Best Practice:** On AWS, **AWS Certificate Manager (ACM)** is the undisputed cloud-native standard for ALB endpoints. It provides automated DNS validation via Route 53 and auto-renews indefinitely without operational overhead.

### 7.2 Automated Let's Encrypt Architecture (If Mandated)
If corporate compliance or external policy requires Let's Encrypt certificates specifically, the recommended serverless architecture avoids maintaining certbot servers:

```mermaid
flowchart LR
    EventBridge["Amazon EventBridge\n(Cron: Every 60 Days)"]
    Lambda["Certbot Lambda Function\n(Python + certbot-dns-route53)"]
    R53["Route 53\n(DNS-01 Challenge)"]
    LE["Let's Encrypt CA"]
    ACM["AWS Certificate Manager / IAM\n(Imported Certificate)"]
    ALB["Application Load Balancer"]

    EventBridge -->|Triggers| Lambda
    Lambda -->|DNS-01 TXT Record| R53
    R53 -->|Validates Domain| LE
    LE -->|Issues Signed Cert| Lambda
    Lambda -->|acm:ImportCertificate| ACM
    ACM -->|Auto-Applies to Listener| ALB
```

1. **EventBridge Rule:** Fires every 60 days.
2. **Lambda Runner:** Executes `certbot` using the `certbot-dns-route53` plugin to fulfill the DNS-01 challenge without needing open port 80 routing.
3. **Import:** The Lambda invokes `boto3.client('acm').import_certificate(...)` with the new certificate and private key.
4. **ALB Update:** The ALB listener certificate is updated automatically via the imported ACM ARN.

---

## 8. Infrastructure as Code (Terraform)

Infrastructure is managed declaratively using **Terraform** (or OpenTofu). Remote state is stored in an S3 bucket with server-side encryption, versioning, and state locking via Amazon DynamoDB.

### Directory Structure
```text
terraform/
├── environments/
│   ├── prod/
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   ├── outputs.tf
│   │   └── terraform.tfvars
│   └── staging/
└── modules/
    ├── vpc/             # Multi-AZ VPC, subnets, route tables, NAT gateways
    ├── security/        # Security groups & IAM roles
    ├── rds/             # Multi-AZ PostgreSQL & subnet groups
    ├── elasticache/     # Redis replication cluster
    ├── alb/             # ALB, listeners, target groups, ACM binding
    ├── ecs/             # ECS Cluster, task definition, Fargate service
    ├── s3_cloudfront/   # S3 buckets for media/static & CloudFront distribution
    └── monitoring/      # CloudWatch dashboards, alarms, SNS topics
```

### Key Terraform Snippet: ECS Fargate Service & Auto-Scaling

```hcl
resource "aws_ecs_service" "shoppin" {
  name                              = "shoppin-prod-service"
  cluster                           = module.ecs_cluster.cluster_id
  task_definition                   = aws_ecs_task_definition.shoppin.arn
  desired_count                     = 2
  launch_type                       = "FARGATE"
  platform_version                  = "LATEST"
  health_check_grace_period_seconds = 60

  network_configuration {
    subnets          = module.vpc.private_app_subnets
    security_groups  = [module.security.ecs_tasks_sg_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = module.alb.target_group_arn
    container_name   = "shoppin-web"
    container_port   = 8000
  }

  deployment_controller {
    type = "ECS"
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
}

# Auto-Scaling Target Tracking on CPU Utilization
resource "aws_appautoscaling_policy" "ecs_cpu_scaling" {
  name               = "shoppin-cpu-target-tracking"
  policy_type        = "TargetTrackingScaling"
  resource_id        = "service/${module.ecs_cluster.cluster_name}/${aws_ecs_service.shoppin.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"

  target_tracking_scaling_policy_configuration {
    target_value       = 70.0
    scale_in_cooldown  = 300
    scale_out_cooldown = 60

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}
```

---

## 9. Monitoring, Observability & Alerting

### 9.1 Logging Architecture
* **Container Logs:** All Django and Daphne logs are emitted as structured JSON to `stdout`/`stderr`.
* **Log Router:** ECS uses the `awslogs` driver sending to CloudWatch Log Group `/ecs/shoppin-prod`.
* **Log Retention:** Set to 90 days in CloudWatch, with automated lifecycle export to S3 Glacier for long-term audit compliance.

### 9.2 Key Performance Indicators & CloudWatch Alarms

| Metric | Source | Alarm Threshold | Severity | Notification Target |
| :--- | :--- | :--- | :--- | :--- |
| **HTTP 5xx Rate** | ALB | &gt; 1% of total requests for 3 mins | High | PagerDuty / On-call Slack |
| **Target Response Time** | ALB | P95 &gt; 1,200ms for 5 mins | Medium | Ops Slack |
| **Unhealthy Host Count** | ALB | &ge; 1 host unhealthy for 2 mins | High | PagerDuty / On-call Slack |
| **RDS CPU Utilization** | RDS | &gt; 80% for 15 mins | Medium | Ops Slack |
| **RDS Free Storage** | RDS | &lt; 15% remaining capacity | High | Ops Slack |
| **Redis Memory Usage** | ElastiCache | &gt; 75% max memory | Medium | Ops Slack |
| **ECS Crash Loops** | ECS | DesiredCount vs RunningCount mismatch | High | PagerDuty / On-call Slack |

### 9.3 Application Performance Monitoring (APM)
* **Sentry** (or AWS X-Ray) integrated into Django for unhandled Python exceptions, slow database query identification, and user session context.
* **Health Check Endpoint (`/health/`):**
  Performs real-time shallow checks on:
  1. PostgreSQL database read/write access (`SELECT 1`).
  2. Redis cache/channel layer responsiveness (`PING`).
  Returns `200 OK` or `503 Service Unavailable`.

---

## 10. Security Hardening & Operational Resilience

### 10.1 Network Segmentation (3-Tier Security Groups)
1. **Public Tier (ALB):** Inbound ports 80 and 443 permitted from `0.0.0.0/0`.
2. **App Tier (ECS Tasks):** Inbound port 8000 permitted **only** from the ALB Security Group ID. No direct internet ingress. Outbound traffic routes through NAT Gateways for external API calls (e.g. Kroger API).
3. **Data Tier (RDS & Redis):** Inbound port 5432 (Postgres) and 6379 (Redis) permitted **only** from the ECS Security Group ID. Zero internet ingress/egress.

### 10.2 AWS WAF (Web Application Firewall)
The ALB is protected by AWS WAF with managed rule groups:
* `AWSManagedRulesCommonRuleSet` (Core protection against OWASP Top 10 vulnerabilities).
* `AWSManagedRulesSQLiRuleSet` (Protection against SQL injection attempts).
* `AWSManagedRulesKnownBadInputsRuleSet` (Blocks known exploit vectors).
* **Rate-Based Rule:** Restricts individual IP addresses to a maximum of 1,000 requests per 5-minute window to prevent scraping and denial-of-service.

### 10.3 Production Multi-Stage Dockerfile Specification
The container build enforces a minimal attack surface and runs under an unprivileged user:

```dockerfile
# Stage 1: Build & Dependencies
FROM python:3.12-slim-bookworm AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Stage 2: Production Distroless / Minimal Runtime
FROM python:3.12-slim-bookworm AS runner
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

# Create unprivileged system user
RUN addgroup --system shoppin && adduser --system --ingroup shoppin shoppin

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY . /app

USER shoppin
EXPOSE 8000

# Run Daphne ASGI server with graceful signal handling
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "config.asgi:application"]
```

---

## 11. Cost Optimization & Sizing Strategy

| Resource | Development / Staging | Production | Estimated Monthly Cost (US-East-1) |
| :--- | :--- | :--- | :--- |
| **Compute** | 1x Fargate (0.5 vCPU, 1 GB) | 2–6x Fargate (1 vCPU, 2 GB) Auto-scaled | \$30 – \$110 |
| **Database** | RDS Postgres `db.t4g.micro` (Single-AZ) | RDS Postgres `db.m7g.large` (Multi-AZ) | \$15 (Staging) / \$180 (Prod) |
| **Cache** | Redis `cache.t4g.micro` | Redis `cache.t4g.small` (Replication Group) | \$12 – \$35 |
| **Networking** | 1x NAT Gateway, 1x ALB | 2x NAT Gateways, 1x ALB | \$70 – \$110 |
| **Storage & Edge** | S3 (50 GB) + CloudFront | S3 (500 GB) + CloudFront + WAF | \$15 – \$35 |
| **Total Estimated** | **~\$140 / month** | **~\$400 – \$550 / month** | |
