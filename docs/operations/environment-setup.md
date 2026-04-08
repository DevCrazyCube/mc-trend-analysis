# Environment Setup Guide

This document describes all environment variables, supported deployment modes, and configuration requirements.

---

## Deployment Modes

| Mode | Purpose | Keys Required |
|------|---------|---------------|
| `demo` | Synthetic data, no external APIs | None |
| `dev` | Real APIs, verbose logging, dev DB | Optional (sources degrade gracefully) |
| `prod` | Production, JSON logging, strict | All delivery channels must be configured |

Set the mode with `ENVIRONMENT=demo|dev|prod`.

---

## Environment Variables

### Required (prod)

| Variable | Description | Example |
|----------|-------------|---------|
| `ENVIRONMENT` | Deployment mode | `prod` |
| `DATABASE_PATH` | SQLite database file path | `/data/mctrend.db` |
| `LOG_LEVEL` | Python log level | `INFO` |
| `LOG_FORMAT` | Log format: `json` or `console` | `json` |

### Data Sources

| Variable | Default | Description |
|----------|---------|-------------|
| `SOLANA_RPC_URL` | `https://api.mainnet-beta.solana.com` | Solana JSON-RPC endpoint |
| `PUMPFUN_API_URL` | (uses built-in default) | Override pump.fun API base URL |
| `NEWSAPI_KEY` | `` (disabled) | NewsAPI.org key — enables news narrative detection |
| `SERPAPI_KEY` | `` (disabled) | SerpAPI key — enables Google Trends detection |

### Alert Delivery

At least one delivery channel should be configured in production.

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | `` (disabled) | Telegram Bot API token |
| `TELEGRAM_CHAT_ID` | `` (disabled) | Telegram chat/channel ID |
| `WEBHOOK_URL` | `` (disabled) | HTTP webhook URL for alert POSTs |
| `WEBHOOK_SECRET` | `` (unsigned) | HMAC-SHA256 signing secret for webhook requests |

Webhook requests include `X-Signature-256: sha256=<hex>` when `WEBHOOK_SECRET` is set.

### Polling & Rate Limits

| Variable | Default | Description |
|----------|---------|-------------|
| `POLLING_INTERVAL_TOKENS` | `30` | Seconds between token polling cycles |
| `POLLING_INTERVAL_EVENTS` | `300` | Seconds between narrative/event polling |
| `ALERT_RATE_LIMIT_PER_10MIN` | `6` | Max push alerts per 10-minute window |
| `MAX_TOKEN_AGE_HOURS` | `4` | Exclude tokens older than this from scoring |
| `CONFIDENCE_FLOOR_FOR_ALERT` | `0.25` | Minimum confidence score to emit any alert |

### Retention

| Variable | Default | Description |
|----------|---------|-------------|
| `CHAIN_SNAPSHOT_RETENTION_HOURS` | `48` | Delete old chain snapshots (keeps latest per token) |
| `SCORED_TOKEN_RETENTION_HOURS` | `72` | Delete old scored_token records (keeps latest per link) |
| `RETIRED_ALERT_RETENTION_HOURS` | `168` | Purge retired/expired alerts (7 days) |
| `ALERT_HISTORY_MAX_ENTRIES` | `50` | Max lifecycle history entries per alert |

### Ingestion Tuning

| Variable | Default | Description |
|----------|---------|-------------|
| `NEWS_SIGNAL_STRENGTH` | `0.6` | Default signal strength for news events |
| `TRENDS_SIGNAL_STRENGTH` | `0.7` | Default signal strength for trend events |
| `TRENDS_GEO` | `US` | Google Trends geographic filter |
| `PUMPFUN_FETCH_LIMIT` | `50` | Tokens per Pump.fun API call |
| `NEWS_PAGE_SIZE` | `10` | Articles per NewsAPI query |

---

## Active vs Disabled Sources

On startup, the system logs which sources are enabled and which are disabled:

```
startup_source_check environment=prod sources_enabled=["pump.fun","newsapi","telegram_delivery"] sources_disabled=["serpapi_trends (SERPAPI_KEY not set)"]
```

**Sources that are disabled degrade gracefully** — the system continues running with whatever sources are available. Source gaps are tracked in the `source_gaps` database table.

---

## Quick Start: Demo Mode

```bash
cp .env.demo.example .env
python -m mctrend.runner --demo --once
# or:
make demo
```

## Quick Start: Docker

```bash
cp .env.prod.example .env
# Edit .env with your real API keys
make build
docker-compose up -d
docker-compose logs -f
```

---

## File Permissions

The process needs:
- **Read/write** access to `DATABASE_PATH` and its parent directory
- **Read** access to the `.env` file

In Docker, the database is stored in `/data` (mounted volume). The container runs as UID 1001.

---

## Schema Versioning

The database includes a `schema_version` table. If you upgrade to a version with schema changes:

1. The system will detect the mismatch and exit with a clear error
2. You must either run the provided migration or delete the database

There is no automatic migration in v1. Manual migrations will be documented in future releases.
