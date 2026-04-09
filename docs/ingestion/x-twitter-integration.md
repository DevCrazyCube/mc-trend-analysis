# X (Twitter) — Emergent Narrative Detection

X is an emergent narrative detection layer. It discovers trending
entities/topics/events on X, detects spikes, and correlates them with
token launches on Solana. It is **not** a fixed-query crypto keyword
scanner.

For the full design rationale, see: `x-emergent-narrative-detection.md`

---

## Role in the System

| Aspect | X (Twitter) | NewsAPI |
|--------|-------------|---------|
| **Role** | Emergent narrative discovery / spike detection | Confirmation / secondary enrichment |
| **Approach** | Broad discovery queries + entity extraction + spike detection | Keyword-based search |
| **Latency** | Seconds to minutes | Minutes to hours |
| **Source type** | `social_media` | `news` |
| **Trust tier** | Tier 1 (noisy, high-volume) | Tier 2 (curated, lower-volume) |

X is registered as an **event adapter** in the ingestion manager. Its output
feeds into the standard normalization → narrative detection → correlation flow.

When both X and news exist for the same narrative:
- X provides early detection via spike signals
- News provides confirmation and raises narrative strength via source diversity

---

## Discovery Model

### How It Works

1. **Broad discovery queries** rotate across categories each cycle (viral
   signals, breaking news, crypto-adjacent, culture/meme, people/events,
   reactions). These are NOT crypto keyword searches — they probe wide
   surfaces to find what's trending.

2. **Entity extraction** (deterministic, no LLM) pulls candidates from
   tweet content: cashtags, hashtags, proper nouns, quoted names.

3. **Spike detection** tracks entity mention velocity across time windows.
   When short-term activity exceeds baseline by a configurable threshold,
   the entity is flagged as spiking.

4. **Token correlation** matches spiking entities against recently launched
   tokens by name, symbol, and cashtag overlap.

5. Spiking entities are injected into the standard narrative flow as events,
   enabling them to participate in scoring, clustering, and alerting.

### Why Queries Still Exist

The X API v2 Recent Search endpoint requires a query parameter — there is
no way to passively enumerate "everything trending." Discovery queries are
an **internal API mechanic**, not the product concept. The intelligence
lives in what we extract from results, not in what we search for.

If a broader API becomes available (trends endpoint, filtered stream), the
extraction/spike/correlation layers are unchanged — only the input funnel
changes.

---

## Query Categories

| Category | Purpose |
|----------|---------|
| `viral` | Catch emerging viral content ("going viral", "blowing up") |
| `breaking` | Catch breaking news/events |
| `crypto` | Retain crypto-adjacent awareness without being narrow |
| `culture` | Meme/culture-driven movements |
| `people` | Person/org/brand narratives |
| `reactions` | Meta-signals of emerging attention |

Queries rotate via round-robin each cycle. Configurable via
`discovery_categories` constructor parameter.

---

## Entity Extraction

Each tweet is processed deterministically (no LLM):

1. **Cashtag extraction** — `$TOKEN` patterns
2. **Hashtag extraction** — `#topic`
3. **Proper noun extraction** — Multi-word capitalized sequences
4. **Quoted name extraction** — Phrases in quotes
5. **Canonicalization** — Uppercase, strip `$#@`, merge similar forms
6. **Noise rejection** — Chronic terms (BTC, ETH, CRYPTO, etc.), too
   short, single-author amplification

---

## Spike Detection

For each extracted entity, the tracker maintains windowed counts:

| Window | Default | Purpose |
|--------|---------|---------|
| Short-term | 30 minutes | Recent activity for spike detection |
| Baseline | 6 hours | Normal activity level |

**Spike condition**: `short_term_rate / max(baseline_rate, floor) >= threshold`

| Spike Ratio | Classification |
|-------------|---------------|
| < 2.0x | Not spiking |
| 2.0x - 5.0x | Mild |
| 5.0x - 15.0x | Emerging |
| 15.0x+ | Viral |

Default thresholds: `spike_threshold=3.0`, `min_mentions=5`,
`min_authors=3`.

---

## Token Correlation

Spiking entities are matched against recent tokens (last 8 hours):

| Match Type | Confidence | Example |
|------------|-----------|---------|
| Name exact | 0.95 | Entity `TRUMP` ↔ Token `TRUMP` |
| Symbol exact | 0.90 | Entity `DOGE` ↔ Symbol `DOGE` |
| Cashtag exact | 0.95 | Entity `$PEPE` ↔ Symbol `PEPE` |
| Name contains | 0.70 | Entity `TRUMP` ↔ Token `TRUMPCOIN` |
| Symbol contains | 0.65 | Entity `SOL` ↔ Symbol `SOLANA` |

---

## Signal Extraction (per tweet)

1. **Engagement scoring** — Weighted combination:
   `score = 0.4 * log1p(retweets) + 0.4 * log1p(likes) + 0.2 * log1p(replies)`
   Normalized to 0.0–1.0 and used as `signal_strength`
2. **Bot/spam filtering** — Deterministic heuristics:
   - Reject tweets with zero followers and high following count
   - Reject tweets that are mostly hashtags/URLs
   - Reject duplicate text (same text posted by different accounts)

---

## Output Schema

The adapter produces event dicts compatible with `normalize_event()`:

```python
{
    "anchor_terms": ["MOONDOG", "SOLANA"],
    "related_terms": ["MEMECOIN", "PUMP"],
    "description": "tweet text (truncated)",
    "source_type": "social_media",
    "source_name": "@author_handle",
    "signal_strength": 0.45,
    "published_at": "2025-01-01T00:00:00Z",
    "url": "https://x.com/user/status/123",
    "raw_text": "full tweet text",
}
```

Spike-derived events use `source_name: "x_spike_detection"` and include
`_spike_metadata` with entity, spike_ratio, spike_class.

---

## Rate Limiting & Cost Control

X API uses a credit-based billing model. The adapter implements:

- **Query rotation** — `queries_per_cycle` (default: 10) queries selected
  from the pool each cycle via round-robin
- **Request budgeting** — configurable `max_requests_per_cycle` (default: 10)
- **Cooldown** — same exponential-backoff pattern as NewsAPI
- **403 handling** — non-retryable, sets `failure_mode=forbidden`

---

## Degraded Mode

When X is unavailable:
- Pipeline continues running
- `pipeline_degraded_mode` log includes X status
- `x_source_available: false`, `x_failure_mode` in cycle summary
- Narrative detection falls back to NewsAPI only
- No crashes, no fake success state

---

## Configuration

| Env Variable | Default | Description |
|---|---|---|
| `X_API_BEARER_TOKEN` | `""` | X API v2 bearer token |
| `X_ENABLED` | `false` | Enable/disable X adapter |
| `X_QUERIES_PER_CYCLE` | `10` | Discovery queries per cycle (rotated) |
| `X_MAX_REQUESTS_PER_CYCLE` | `10` | Max API calls per pipeline cycle |
| `X_SIGNAL_STRENGTH` | `0.5` | Base signal strength for X events |
| `X_COOLDOWN_AFTER` | `2` | Consecutive 429s before cooldown |
| `X_COOLDOWN_SECONDS` | `60.0` | Base cooldown duration |
| `X_MAX_COOLDOWN_SECONDS` | `900.0` | Max cooldown duration |
| `X_RATE_LIMIT_STATE_PATH` | `data/x_ratelimit_state.json` | Persistent cooldown state file |

---

## Cycle Summary Fields

| Field | Type | Description |
|---|---|---|
| `x_source_available` | bool | Whether X adapter is healthy |
| `x_failure_mode` | str | healthy / rate-limited / forbidden / unavailable |
| `x_entities_extracted` | int | Candidate entities extracted this cycle |
| `x_spikes_detected` | int | Entities exceeding spike threshold |
| `x_spike_token_matches` | int | Spikes matched to tokens |

---

## Logging

| Event | Level | When |
|---|---|---|
| `x_fetch_complete` | INFO | After successful discovery fetch cycle |
| `x_items_filtered` | INFO | After spam/bot/dedup filtering |
| `x_entity_rejected` | DEBUG | Candidate entity rejected (with reason) |
| `x_entity_tracking_started` | DEBUG | New entity added to tracker |
| `x_spike_detected` | INFO | Entity exceeds spike threshold |
| `x_spike_not_strong_enough` | DEBUG | Entity active but below threshold |
| `x_entity_linked_to_token` | INFO | Spiking entity matched to a token |
| `x_discovery_cycle_complete` | INFO | Summary with entity/spike counts |
| `x_entities_pruned` | DEBUG | Stale entities removed from tracker |
| `x_rate_limited` | WARNING | On 429 response |
| `x_forbidden` | WARNING | On 403 response |
| `x_cooldown_active` | INFO | When fetch skipped due to cooldown |

---

## Limitations

1. **Query-bounded discovery.** The Basic tier requires a query. Discovery
   is as broad as the query pool allows.
2. **No trending topics API.** True trending data requires elevated access.
3. **Baseline accuracy improves over time.** Initial cycles have limited
   history for spike detection.
4. **X signals require corroboration.** Never sufficient alone for scores
   above `watch` tier.
