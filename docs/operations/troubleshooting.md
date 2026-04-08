# Troubleshooting Guide

---

## Startup Failures

### `[STARTUP VALIDATION FAILED] ENVIRONMENT=... is not valid`

The `ENVIRONMENT` variable is set to an unrecognized value.

**Fix:** Set `ENVIRONMENT` to one of: `demo`, `dev`, `prod`.

---

### `[STARTUP VALIDATION FAILED] Cannot create database directory`

The process cannot write to the directory containing `DATABASE_PATH`.

**Fix:**
- Check that the directory exists and is writable by the process user
- In Docker, ensure the `/data` volume is mounted and the container user (UID 1001) can write to it

---

### `[SCHEMA VERSION ERROR] Database schema version X does not match expected version Y`

The database file was created by an older (or newer) version of the system.

**Fix:**
- **For development:** Delete the database file and restart — the system will reinitialize
- **For production:** Contact the maintainer for a migration script. Do not delete production data without a backup.

---

## No Alerts Being Generated

### All sources healthy but no alerts

1. Check that narratives exist: `python -m mctrend.runner --status`
2. If `Active alerts: 0` and `Narratives (EMERGING): 0`, no narratives have been detected
3. Verify that `NEWSAPI_KEY` and/or `SERPAPI_KEY` are set, or run with `--demo`
4. Check `confidence_floor_for_alert` — default is 0.25; lower it for testing

### Tokens scored but no alerts

The alert classifier uses thresholds. Tokens with very low scores (e.g., all missing data) may classify as `discard` or `ignore`. These do not generate alerts.

Check the scored token records and alert types logged at `DEBUG` level.

---

## NewsAPI Rate-Limit Cooldown

When NewsAPI returns HTTP 429 (Too Many Requests), the adapter enters an
exponential-backoff cooldown.  During cooldown all fetch calls return empty
immediately — no HTTP requests are made.

**Cooldown schedule:**

| Episode | Duration |
|---------|----------|
| 1 | 60 s |
| 2 | 120 s |
| 3 | 240 s |
| … | doubles, capped at 900 s |

**Cooldown persists across restarts.**  The deadline is written to
`data/newsapi_ratelimit_state.json` (configurable via
`NEWSAPI_RATE_LIMIT_STATE_PATH`).  On restart the adapter reads this file and
honours any unexpired deadline.  To manually clear a stuck cooldown, delete
the state file and restart.

**Log to watch:**

```
newsapi_cooldown_restored_from_state  cooldown_remaining_seconds=... state_path=...
newsapi_cooldown_active               cooldown_remaining_seconds=... cooldown_episodes=...
newsapi_entering_cooldown             cooldown_seconds=... cooldown_episode=...
```

**429 is not retried.**  A 429 response triggers cooldown immediately — no
same-cycle retry attempts.  (Network errors and 5xx responses are still
retried up to 3 times with backoff.)

---

## Pipeline Degraded Mode (News Source Unavailable)

When NewsAPI is offline or cooling down, the pipeline logs:

```
pipeline_degraded_mode  reason="newsapi rate-limited (cooldown 240s remaining, episode 2)"
                        tokens_available=true
                        hint="Tokens will be ingested but narrative-driven scoring will be zero..."
```

The cycle summary will show:
```json
{
  "news_source_available": false,
  "narrative_path_offline": true,
  "scoring_limited_reason": "newsapi rate-limited (cooldown 240s remaining, episode 2)",
  "tokens_ingested": 12,
  "tokens_scored": 0,
  "competition_outcomes": []
}
```

This is expected behaviour.  Tokens continue to be ingested and stored.
Scoring resumes once the news source recovers and fresh narratives are available.

---

## Source Gaps

Source gaps are recorded when an adapter fails to fetch data. View them with:

```bash
python -m mctrend.runner --status
```

Or query directly:

```sql
SELECT source_name, started_at, ended_at FROM source_gaps WHERE ended_at IS NULL;
```

**Gap lifecycle:**
- A gap is **opened once** when a source transitions from healthy → unavailable.
- While the source remains unavailable, no additional gap records are created.
- The gap is **closed** when the source recovers on the next successful cycle.
- If the source fails again after recovery, a **new gap** is opened.

This means one continuous outage = exactly one gap record in the database.

Gaps close automatically when the source recovers in the next successful cycle.

### Common gap causes

| Source | Common Cause |
|--------|-------------|
| `pump.fun` | Pump.fun API rate limit, maintenance, or outage |
| `newsapi` | API key invalid, quota exceeded, or rate-limit cooldown |
| `serpapi_trends` | API key invalid or quota exceeded |
| `solana_rpc` | RPC endpoint rate limit; switch to a dedicated RPC provider |

---

## Pump.fun Returns 503

Pump.fun's public API endpoint is unstable. The system retries automatically (3 attempts with exponential backoff). If all retries fail, the source is marked unhealthy for the cycle and a gap is recorded.

**Options:**
- Accept the degraded state — the system continues scoring tokens from the previous cycle
- Configure a dedicated pump.fun API endpoint via `PUMPFUN_API_URL`

---

## Telegram Delivery Not Working

1. Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set correctly
2. Ensure the bot has permission to post to the specified chat
3. Check the `alert_deliveries` table for failure reasons:
   ```sql
   SELECT alert_id, status, failure_reason FROM alert_deliveries ORDER BY attempted_at DESC LIMIT 20;
   ```
4. The system retries Telegram 3 times before recording a failure

---

## Webhook Signature Verification

If your webhook receiver is rejecting requests, verify the HMAC:

1. The signature is in the `X-Signature-256` header as `sha256=<hex>`
2. It is computed over the raw JSON body bytes using `HMAC-SHA256(WEBHOOK_SECRET, body)`
3. Ensure `WEBHOOK_SECRET` is identical on both sides
4. Compare the full body bytes — do not re-serialize the JSON

Example Python verification:
```python
import hashlib, hmac

def verify(secret: str, body: bytes, signature: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
```

---

## Database Growing Unexpectedly

The retention policy runs every cycle. Check current DB size:

```bash
python -m mctrend.runner --status
```

If the DB is large:
1. Lower `CHAIN_SNAPSHOT_RETENTION_HOURS`, `SCORED_TOKEN_RETENTION_HOURS`, or `RETIRED_ALERT_RETENTION_HOURS`
2. Restart to apply the new retention windows — they take effect on the next cycle

---

## High Memory Usage

Unbounded queries now have LIMIT clauses. If memory is still high:
- Reduce `POLLING_INTERVAL_TOKENS` to process fewer tokens per cycle
- Check for accumulating un-linked tokens with `python -m mctrend.runner --status`
- Tokens that never link to a narrative stay in `new` status and are re-queried each cycle — this is intentional (they may link later), but tokens older than `MAX_TOKEN_AGE_HOURS` are excluded from scoring

---

## Logs

**Console format (dev):**
```
2026-04-08T12:00:00Z INFO pipeline_cycle_start cycle=1
```

**JSON format (prod):**
```json
{"event": "pipeline_cycle_start", "level": "info", "cycle": 1, "timestamp": "2026-04-08T12:00:00Z"}
```

Set `LOG_LEVEL=DEBUG` to see per-token scoring details and delivery routing decisions.
