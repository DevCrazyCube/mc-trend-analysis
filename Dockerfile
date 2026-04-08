FROM python:3.11-slim

LABEL maintainer="mc-trend-analysis"
LABEL description="Real-time trend intelligence and alerting system for Pump.fun / Solana memecoins"

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer caching)
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]" || pip install --no-cache-dir -e .

# Copy source
COPY src/ ./src/
COPY docs/ ./docs/

# Data directory for SQLite
RUN mkdir -p /data && chmod 755 /data

# Non-root user for security
RUN useradd --system --uid 1001 --gid 0 --no-create-home mctrend && \
    chown -R mctrend:0 /app /data
USER mctrend

# Health check — verifies system can start and query status
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -m mctrend.runner --status --env /dev/null || exit 1

ENV DATABASE_PATH=/data/mctrend.db
ENV LOG_FORMAT=json
ENV LOG_LEVEL=INFO
ENV ENVIRONMENT=prod

ENTRYPOINT ["python", "-m", "mctrend.runner"]
CMD []
