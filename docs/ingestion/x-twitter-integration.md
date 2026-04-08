# X (Twitter) Integration

X is a first-class, real-time narrative signal layer. It detects emerging
narratives earlier than news sources and correlates them with on-chain token
events.

---

## Role in the System

| Aspect | X (Twitter) | NewsAPI |
|--------|-------------|---------|
| **Role** | Early signal / primary narrative detection | Confirmation / secondary enrichment |
| **Latency** | Seconds to minutes | Minutes to hours |
| **Source type** | `social_media` | `news` |
| **Trust tier** | Tier 1 (noisy, high-volume) | Tier 2 (curated, lower-volume) |

X is registered as an **event adapter** in the ingestion manager. Its output
feeds into the same normalization → narrative detection → correlation flow
as news events.

When both X and news exist for the same narrative:
- X provides early detection
- News provides confirmation and raises narrative strength via source diversity

---

## Adapter Modes

### Polling Mode (default)

Queries the X API v2 Recent Search endpoint at each pipeline cycle.
Configurable query terms target Solana/memecoin activity.

- Uses `GET /2/tweets/search/recent`
- Query terms are combined into X search queries
- Results are deduplicated by tweet ID
- Rate-limited by X API credit budget

### Search Mode (on-demand, future)

Used for narrative context enrichment when a new token is detected or
narrative needs backfill. Not implemented in the initial version.

### Stream Mode (future)

Real-time filtered stream connection. Requires elevated X API access.
Not implemented in the initial version — the polling mode with short
intervals provides adequate latency for the current pipeline.

---

## Signal Extraction

Each tweet is processed deterministically (no LLM):

1. **Cashtag extraction** — `$TOKEN` patterns become anchor terms
2. **Hashtag extraction** — `#solana`, `#memecoin` etc. become related terms
3. **Term extraction** — Same stop-word filtering as NewsAPI adapter
4. **Engagement scoring** — Weighted combination:
   `score = 0.4 * log1p(retweets) + 0.4 * log1p(likes) + 0.2 * log1p(replies)`
   Normalized to 0.0–1.0 and used as `signal_strength`
5. **Bot/spam filtering** — Deterministic heuristics:
   - Reject tweets with zero followers and high following count
   - Reject tweets that are mostly hashtags/URLs
   - Reject duplicate text (same text posted by different accounts)

---

## Output Schema

The adapter produces event dicts compatible with `normalize_event()`:

```python
{
    "anchor_terms": ["MOONDOG", "SOLANA"],      # from cashtags + key terms
    "related_terms": ["MEMECOIN", "PUMP"],       # from hashtags + secondary terms
    "description": "tweet text (truncated)",     # first 120 chars
    "source_type": "social_media",
    "source_name": "@author_handle",
    "signal_strength": 0.45,                     # engagement-weighted
    "published_at": "2025-01-01T00:00:00Z",
    "url": "https://x.com/user/status/123",
    "raw_text": "full tweet text",
    "_title": "tweet text (truncated)",
    "_description": "",
    "_source_name": "@author_handle",
}
```

---

## Correlation with Tokens

X narratives enter the standard correlation flow:

1. Cashtags (`$MOONDOG`) become anchor terms (`MOONDOG`)
2. The correlation linker's Layer 1 (exact match) links token name `MOONDOG`
   to anchor term `MOONDOG` with high confidence (0.95)
3. Abbreviation and related-term matching (Layers 2–3) work as usual

No changes to the correlation linker are required — X events produce the
same `anchor_terms` / `related_terms` structure that the linker already
consumes.

---

## Rate Limiting & Cost Control

X API uses a credit-based billing model. The adapter implements:

- **Request budgeting** — configurable `max_requests_per_cycle` (default: 5)
- **Cooldown** — same exponential-backoff pattern as NewsAPI:
  - After N consecutive 429s → enter cooldown
  - Persisted to disk for restart safety
- **Adaptive query strategy** — fewer high-signal queries preferred
  over broad noisy queries

---

## Degraded Mode

When X is unavailable:
- Pipeline continues running
- `pipeline_degraded_mode` log includes X status
- Summary includes `x_source_available: false`
- Narrative detection falls back to NewsAPI only

---

## Configuration

| Env Variable | Default | Description |
|---|---|---|
| `X_API_BEARER_TOKEN` | `""` | X API v2 bearer token |
| `X_ENABLED` | `false` | Enable/disable X adapter |
| `X_MAX_REQUESTS_PER_CYCLE` | `5` | Max API calls per pipeline cycle |
| `X_SIGNAL_STRENGTH` | `0.5` | Base signal strength for X events |
| `X_COOLDOWN_AFTER` | `2` | Consecutive 429s before cooldown |
| `X_COOLDOWN_SECONDS` | `60.0` | Base cooldown duration |
| `X_MAX_COOLDOWN_SECONDS` | `900.0` | Max cooldown duration |
| `X_RATE_LIMIT_STATE_PATH` | `data/x_ratelimit_state.json` | Persistent cooldown state file |

Query terms are configured via `X_QUERY_TERMS` (comma-separated) or default
to Solana/memecoin-specific search terms.

---

## Logging

| Event | Level | When |
|---|---|---|
| `x_fetch_complete` | INFO | After successful fetch cycle |
| `x_items_filtered` | INFO | After spam/bot/dedup filtering |
| `x_rate_limited` | WARNING | On 429 response |
| `x_cooldown_active` | INFO | When fetch skipped due to cooldown |
| `x_entering_cooldown` | WARNING | When cooldown period begins |
| `x_cooldown_restored_from_state` | WARNING | When startup restores persisted cooldown |
| `x_source_unavailable` | WARNING | When fetch fails for non-429 reasons |

---

## Future Extensions (not implemented)

The adapter is structured so the following can be added later:

- **Influencer weighting** — `signal_strength` multiplier based on author metrics
- **Narrative clustering** — grouping related tweets into narrative threads
- **Cross-source merging** — linking X narratives with news narratives
  covering the same topic
- **Stream mode** — real-time filtered stream for lower-latency detection
