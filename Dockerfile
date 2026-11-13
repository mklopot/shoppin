# ==============================================================================
# Shoppin Production Multi-Stage Dockerfile
# Python 3.12 + Daphne ASGI Server (HTTP & WebSockets)
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Dependency Builder
# ------------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /install

# Install build dependencies required for compiling wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .

# Install dependencies into a separate prefix so we can copy only artifacts
RUN pip install --upgrade pip setuptools wheel && \
    pip install --prefix=/install/build .

# ------------------------------------------------------------------------------
# Stage 2: Minimal Runtime Container
# ------------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runner

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app

# Install runtime shared libraries (Postgres client library, curl for health check)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder stage
COPY --from=builder /install/build /usr/local

# Create dedicated unprivileged system user
RUN addgroup --system --gid 1001 shoppin && \
    adduser --system --uid 1001 --gid 1001 --home /app shoppin

# Copy application source code
COPY . /app

# Create staticfiles and media directories with correct permissions
RUN mkdir -p /app/staticfiles /app/media && \
    chown -R shoppin:shoppin /app

# Make entrypoint executable
RUN chmod +x /app/scripts/entrypoint.sh

USER shoppin

EXPOSE 8000

# Health check verifies the Daphne ASGI server is answering
HEALTHCHECK --interval=20s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/health/ || exit 1

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "config.asgi:application"]
