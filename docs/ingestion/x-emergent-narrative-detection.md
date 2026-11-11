# X Emergent Narrative Detection

Design document for the X subsystem pivot from query-based crypto keyword
search to emergent narrative detection.

---

## Why the Query-Based Model Is Being Removed

The previous X adapter operated as a fixed-query crypto keyword scanner:
- Hardcoded search terms: `"solana memecoin launch"`, `"pump.fun token"`, etc.
- Each cycle queried these exact phrases via `GET /2/tweets/search/recent`
- Only discovered narratives that matched pre-authored crypto-specific phrases

This is fundamentally limited:

1. **Misses the real opportunity.** The system should detect *any* spiking
   narrative on X and then check whether tokens are launching around it.
   Example: "Trump is dead" starts trending -> tokens named TRUMP appear on
   pump.fun -> the system should link them. The old model never sees
   non-crypto narratives.

2. **Static by construction.** The query list is hand-maintained. New
   narratives, memes, events, and cultural moments can't be discovered
   unless someone manually adds a query.

3. **Redundant with on-chain data.** Searching for "solana memecoin launch"
   on X returns the same information already captured by PumpPortal. The
   value of X is detecting *external* narratives that drive token creation,
   not echoing token creation back to itself.

---

## Target Model: Emergent Narrative Detection

```
X source
  -> collect raw posts from the widest viable discovery surface
  -> extract candidate narratives / entities / topics
  -> normalize / deduplicate / reject noise
  -> track mention velocity over time windows
  -> detect spikes vs baseline
  -> correlate with token launches and token metadata
  -> contribute explainable score
```

The system is narrative-first, not query-first. Queries are an internal API
mechanic, not the product concept.

---

## X API v2 Reality Check

### Available Endpoint

`GET /2/tweets/search/recent` (Basic/Pro tier):
- Requires a query string (cannot enumerate "all trending topics")
- Returns tweets from the **last 7 days**
- Rate limits: 450 requests/15 min (Basic), scaled by tier
- Max 100 results per request
- Supports boolean operators, hashtag/cashtag matching, entity expansion

### What Is NOT Available (Basic Tier)

- **Trending topics endpoint** (`GET /2/trends/by/woeid`) -- requires
  elevated access
- **Filtered stream** -- requires elevated access
- **Full-archive search** -- requires Academic/Enterprise tier
- **Counts endpoint** -- requires elevated access
- **Sample stream** -- requires elevated access

### Honest Assessment

True global narrative discovery (zero-query, discover anything) is **not
possible** with the Basic tier Recent Search endpoint. Every request
requires a query parameter.

### Design Response

Since queries are mechanically required, we restructure them:

1. **Queries become a rotating discovery surface**, not a fixed product
   concept. They are broad, category-based probes designed to catch diverse
   topics -- not crypto keyword searches.

2. **The entity/topic extraction layer is the real product.** Queries are
   just the input funnel. The intelligence lives in what we extract from
   the results, not in what we search for.

3. **Queries rotate and adapt.** The system uses a large pool of broad
   discovery queries and rotates through subsets each cycle. This
   maximizes the discovery surface within the API budget.

4. **The architecture separates discovery from extraction.** If a broader
   API becomes available later (stream, trends), the extraction/spike/
   correlation layers are unchanged -- only the discovery input changes.

---

## Discovery Query Design

### Principle

Queries should be:
- **Broad** -- capture diverse topics, not just crypto
- **Entity-rich** -- likely to return posts mentioning people, brands,
  events, movements
- **Current-event biased** -- favor recency and virality
- **Rotating** -- different subsets each cycle to maximize coverage

### Query Categories

| Category | Example Queries | Why |
|----------|----------------|-----|
| Viral/trending signals | `"going viral" lang:en`, `"breaking:" lang:en` | Catches emerging stories |
| Crypto-adjacent | `"solana" lang:en`, `"pump.fun" lang:en` | Retains crypto awareness without being narrow |
| Culture/meme signals | `"meme coin" OR "memecoin" lang:en` | Captures meme-driven token creation |
| People/events | `"just announced" lang:en`, `"breaking news" lang:en` | Catches person/event narratives |
| Reactions/sentiment | `"everyone is talking about" lang:en` | Meta-signal of emerging attention |
| High-engagement | `min_retweets:100 lang:en` (if supported) | Finds viral content directly |

### Rotation Strategy

- Maintain a pool of ~30-50 broad discovery queries across categories
- Each cycle, select a configurable subset (default: 10)
- Rotation is deterministic by cycle index (round-robin + shuffle)
- Categories are weighted so each cycle covers multiple categories
- Queries are stored in configuration, not hardcoded

---

## Entity/Topic Extraction Pipeline

### Stage 1: Raw Content Processing

For each tweet returned by discovery queries:

1. **Spam/bot filter** (existing, kept) -- reject low-quality content
2. **Deduplication** (existing, kept) -- by tweet ID and text fingerprint
3. **Entity extraction** (new) -- deterministic, no LLM:
   - Proper nouns (capitalized words not at sentence start, 2+ chars)
   - Cashtags (`$TOKEN`)
   - Hashtags (`#topic`)
   - @mentions (for person-entity linkage)
   - Quoted names ("Operation X", 'Project Y')
   - Bigrams/trigrams from high-frequency co-occurring terms

### Stage 2: Candidate Narrative Construction

Extracted entities are grouped into **candidate narratives**:

```python
{
    "candidate_id": "uuid",
    "entity": "TRUMP",                    # normalized canonical form
    "entity_type": "person",              # person | brand | event | hashtag | cashtag | topic
    "variants": ["Trump", "TRUMP", "trump", "#Trump"],
    "mention_count": 15,                  # within current cycle
    "first_seen": "2025-01-01T00:00:00Z",
    "sources": [...],                     # tweet authors
    "sample_texts": [...],                # representative tweets (for debugging)
    "engagement_total": 4500,             # sum of engagement across mentions
}
```

### Stage 3: Noise Rejection

Candidates are rejected if they match:

- **Chronic terms**: always-present words that are not emergent
  (`"bitcoin"`, `"ethereum"`, `"crypto"`, `"nft"`, `"gm"`)
- **Bot amplification**: same entity appearing only from bot-pattern accounts
- **Low engagement**: total engagement below threshold
- **Single-source**: only one unique author mentioning the entity
- **Too generic**: single common English words (`"just"`, `"new"`, `"big"`)

Chronic terms are configurable. Rejection reasons are logged.

### Stage 4: Normalization and Deduplication

- Case-insensitive canonical form (e.g. `"Trump"` and `"TRUMP"` -> `"TRUMP"`)
- Strip leading `$`, `#`, `@`
- Merge candidates with high string similarity (>80% Jaccard on character
  trigrams)
- Track all variant forms seen

---

## Spike Detection

### Windowed Counting

For each entity, maintain counts across rolling time windows:

| Window | Purpose |
|--------|---------|
| Current cycle | Raw count this cycle |
| Short-term (30 min) | Recent activity |
| Baseline (6 hours) | Normal activity level |

### Spike Score

```
spike_ratio = short_term_rate / max(baseline_rate, floor)
```

Where `floor` is a minimum baseline to prevent division-by-zero inflation
(configurable, default: 0.1 mentions/min).

An entity is considered **emerging** when:

1. `spike_ratio >= spike_threshold` (default: 3.0x baseline)
2. `mention_count >= min_mentions` (default: 5 in short-term window)
3. `unique_authors >= min_authors` (default: 3)

### Spike Classification

| Spike Ratio | Classification |
|-------------|---------------|
| < 2.0x | Not spiking |
| 2.0x - 5.0x | Mild interest |
| 5.0x - 15.0x | Emerging |
| 15.0x+ | Viral |

Classification is informational for logging/debugging. The spike_ratio
itself is the signal used downstream.

---

## Token Correlation

When an entity is spiking, the system checks for token-launch overlap:

### Overlap Signals

1. **Name match**: Token name contains or matches the spiking entity
   (uses existing `normalize_token_name()` + Jaccard similarity)
2. **Symbol match**: Token symbol matches entity or its abbreviation
3. **Cashtag match**: Entity was originally a cashtag (`$TRUMP`) that
   matches a token
4. **Timing proximity**: Token launched within a configurable window of
   the spike onset (default: 2 hours before to 6 hours after)
5. **Co-mention**: The entity and a token address/name appear in the
   same tweets

### Correlation Output

```python
{
    "entity": "TRUMP",
    "spike_ratio": 12.5,
    "spike_class": "emerging",
    "matched_tokens": [
        {
            "token_id": "...",
            "token_name": "TRUMP",
            "match_type": "name_exact",
            "match_confidence": 0.95,
            "timing_offset_hours": 0.5,
        }
    ],
    "overlap_signals": ["name_match", "timing_proximity", "cashtag_mention"],
}
```

This feeds into the existing narrative -> token-narrative-link -> scoring
flow. The spiking entity becomes (or merges into) a narrative record.

---

## Scoring Contribution

Emergent X narratives contribute to existing dimensions:

### Narrative Relevance (Dimension 1)

- `source_type_count` increases when X social_media is present alongside
  news sources -> higher diversity component
- `match_confidence` uses the same correlation confidence as before
- No changes to the scoring formula

### New Signal: Emergence Strength

The spike_ratio from X is exposed as an additional signal in the narrative
metadata:

- `x_spike_ratio`: numeric value passed through narrative -> scoring
- Used by `narrative_strength` computation (via velocity/source signals)
- Not a standalone dimension; contributes through existing channels

### Bounded Contribution

Per existing rules:
- X signals alone are never sufficient for scores above `watch` tier
- X data requires corroboration from at least one other source type
- No change to this policy

---

## Persistence

### Entity State Table (new)

```sql
CREATE TABLE IF NOT EXISTS x_entity_state (
    entity_id TEXT PRIMARY KEY,
    entity TEXT NOT NULL,
    entity_type TEXT DEFAULT 'topic',
    canonical_form TEXT NOT NULL,
    variants TEXT,           -- JSON array
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    baseline_rate REAL DEFAULT 0.0,
    short_term_count INTEGER DEFAULT 0,
    total_count INTEGER DEFAULT 0,
    spike_ratio REAL DEFAULT 0.0,
    is_spiking INTEGER DEFAULT 0,
    is_chronic INTEGER DEFAULT 0,
    linked_narrative_id TEXT,
    updated_at TEXT NOT NULL
);
```

This table enables cross-cycle state. Baseline rates accumulate over time,
giving increasingly accurate spike detection.

### Pruning

Entities not seen in 24 hours are pruned. Chronic entities are retained
with `is_chronic = 1` to prevent re-evaluation.

---

## Degraded Mode

If X auth/access is broken:
- Pipeline continues running normally
- `x_source_available: false` in cycle summary (existing)
- `x_failure_mode: "forbidden" | "rate-limited" | "unavailable"` (existing)
- Log: `"emergent X narrative detection is offline"` (new)
- No crashes, no fake success state
- Narrative detection falls back to NewsAPI + on-chain only

---

## Configuration

### Removed

| Variable | Reason |
|----------|--------|
| `X_QUERY_TERMS` | Replaced by discovery query pool |

### New

| Variable | Default | Description |
|----------|---------|-------------|
| `X_DISCOVERY_CATEGORIES` | (see defaults) | JSON map of category -> query list |
| `X_QUERIES_PER_CYCLE` | `10` | How many discovery queries per cycle |
| `X_SPIKE_THRESHOLD` | `3.0` | Spike ratio threshold for emergence |
| `X_SPIKE_MIN_MENTIONS` | `5` | Minimum mentions in short-term window |
| `X_SPIKE_MIN_AUTHORS` | `3` | Minimum unique authors for spike |
| `X_BASELINE_WINDOW_HOURS` | `6.0` | Hours for baseline rate computation |
| `X_SHORT_TERM_WINDOW_MINUTES` | `30.0` | Short-term spike detection window |
| `X_ENTITY_PRUNE_HOURS` | `24.0` | Hours before inactive entities are pruned |

### Retained (unchanged)

| Variable | Description |
|----------|-------------|
| `X_API_BEARER_TOKEN` | Bearer token |
| `X_ENABLED` | Enable/disable toggle |
| `X_MAX_REQUESTS_PER_CYCLE` | API budget per cycle |
| `X_SIGNAL_STRENGTH` | Base signal strength |
| `X_COOLDOWN_AFTER` | 429 threshold |
| `X_COOLDOWN_SECONDS` | Base cooldown |
| `X_MAX_COOLDOWN_SECONDS` | Max cooldown |
| `X_RATE_LIMIT_STATE_PATH` | Persistent state file |

---

## Observability

| Log Event | Level | When |
|-----------|-------|------|
| `x_entity_extracted` | DEBUG | Candidate entity found in tweet |
| `x_entity_rejected` | DEBUG | Candidate rejected as noise (with reason) |
| `x_entity_normalized` | DEBUG | Entity canonicalized / merged |
| `x_spike_detected` | INFO | Entity exceeds spike threshold |
| `x_spike_not_strong_enough` | DEBUG | Entity active but below threshold |
| `x_entity_linked_to_token` | INFO | Spiking entity matched to a token |
| `x_token_boosted_by_spike` | INFO | Token score influenced by X spike |
| `x_discovery_cycle_complete` | INFO | Cycle summary with entity/spike counts |
| `x_emergent_detection_offline` | WARNING | X source unavailable |

---

## Limitations and Future Path

### Current Limitations

1. **Query-bounded discovery.** The Basic tier requires a query. We cannot
   passively observe "everything happening on X." Discovery is as broad as
   our query pool allows.

2. **No trending topics API.** True trending topic data requires elevated
   access. The current approach approximates it by probing diverse query
   categories.

3. **Rate budget constraints.** 450 requests/15 min at Basic tier. With
   10 queries/cycle and 2-min cycle interval, we use ~75 requests/15 min
   -- well within budget but limiting breadth.

4. **Baseline accuracy improves over time.** Initial cycles have no
   baseline history, so spike detection is less accurate. After a few
   hours of operation, baselines stabilize.

### Future Improvements (Not Implemented Now)

- **Trending topics endpoint** -- if elevated access is obtained, replace
  discovery queries with real trending data
- **Filtered stream** -- if elevated access is obtained, replace polling
  with real-time entity extraction from stream
- **Adaptive query generation** -- use spiking entities to generate
  follow-up queries in subsequent cycles (positive feedback loop)
- **Cross-source spike confirmation** -- combine X spikes with Google
  Trends or news spikes for higher confidence
- **Influencer weighting** -- weight entities by author influence

---

## Implementation Phases

### Phase B: Remove Query-Centric Runtime

- Strip `X_QUERY_TERMS` from settings, adapter, runner, docs
- Replace with discovery query pool and rotation
- Adapter no longer takes `query_terms` constructor param
- Tests updated

### Phase C: Entity Extraction and Normalization

- `XEntityExtractor` class: extracts entities from tweet text
- Canonical form normalization, variant tracking
- Noise rejection with configurable chronic terms
- Unit tests for extraction, normalization, rejection

### Phase D: Spike Detection

- `XEntityTracker` class: windowed counts, baseline, spike ratio
- `x_entity_state` table for cross-cycle persistence
- Spike detection logic with configurable thresholds
- Unit tests for windowed counting, spike classification

### Phase E: Token Correlation and Scoring

- Connect spiking entities to existing narrative/correlation flow
- Name/symbol/cashtag/timing overlap signals
- Bounded score contribution through existing dimensions
- Integration tests

### Phase F: Metrics and Docs

- Cycle summary fields for entity/spike counts
- Updated docs: source-types.md, troubleshooting.md, .env.dev.example
- Final observability pass
