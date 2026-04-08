# Ingestion Patterns

This document defines reusable patterns for the ingestion layer: polling, streaming, deduplication, and normalization. These are implementation-level patterns, not abstractions — they describe how to approach common problems correctly.

---

## Pattern 1: Polling with Gap Detection

**Problem:** A source must be polled repeatedly. If polling fails, we must know which time window has a gap.

**Pattern:**
1. Before polling: record `poll_attempt_at` timestamp
2. Fetch data from source
3. On success: record `last_successful_poll_at` and process data
4. On failure: create a `SourceGap` record with start = last successful poll, end = TBD
5. On recovery: update the `SourceGap` record with end time

**Key requirement:** `SourceGap` records are created immediately on failure, not retrospectively. This way, if the system also goes down, the gap is still recorded.

**Implementation sketch:**
```python
def poll_source(source_name: str, fetch_fn: Callable) -> list[RawRecord]:
    try:
        records = fetch_fn()
        mark_source_healthy(source_name)
        return records
    except SourceError as e:
        open_source_gap(source_name, reason=str(e))
        logger.warning("Source %s unavailable: %s", source_name, e)
        return []  # return empty, don't raise — caller handles empty gracefully
```

---

## Pattern 2: Idempotent Record Ingestion

**Problem:** The same record may arrive from multiple sources or multiple polls. Creating duplicates corrupts downstream processing.

**Pattern:**
1. Define a deterministic deduplication key for each record type
   - TokenRecord: `address` (Solana contract address)
   - EventRecord: combination of anchor terms + time window
   - SocialRecord: source + subject_id + sampled_at (rounded to nearest minute)
2. Before creating a new record, check if the key already exists
3. If exists: update fields that may have changed (attention score, freshness), do not create duplicate
4. If not exists: create new record

**Key requirement:** The deduplication key must be derived from the content, not from an auto-generated ID. Auto-generated IDs produce duplicates because the check happens after ID generation.

---

## Pattern 3: Partial Data Handling

**Problem:** A source returns some required fields but not others. The record is incomplete but may still be worth processing.

**Pattern:**
1. Define which fields are required vs. optional (see `docs/rules/data-quality-rules.md`)
2. Validate required fields: if any are missing, reject the record (log the rejection)
3. For optional fields: set to `null` explicitly, add field name to `data_gaps[]`
4. Pass the record downstream with its gaps; let the scoring layer handle them

**What NOT to do:**
```python
# Wrong: substituting defaults silently
holder_count = data.get("holders", 0)  # 0 is wrong — we don't know it's 0
```

**What to do:**
```python
# Correct: explicit null with gap tracking
holder_count = data.get("holders", None)
if holder_count is None:
    data_gaps.append("holder_count")
```

---

## Pattern 4: Streaming with Reconnect

**Problem:** WebSocket streams from token platforms are unreliable. The connection drops. Messages may be missed.

**Pattern:**
1. Maintain a connection state: `connected`, `reconnecting`, `failed`
2. On disconnect: enter `reconnecting` state, attempt reconnect with exponential backoff
3. On reconnect: if sequence IDs or timestamps are available from the source, fetch missed events for the gap period
4. If missed events cannot be recovered: create a `SourceGap` record for the disconnect period
5. Log every reconnect attempt and its outcome

**Reconnect backoff:**
```
attempt 1: wait 2 seconds
attempt 2: wait 4 seconds
attempt 3: wait 8 seconds
attempt 4: wait 16 seconds
attempt 5+: wait 30 seconds (cap)
```

After N consecutive failures (configurable; default: 10), switch to polling fallback and alert the operator.

---

## Pattern 5: Rate Limit Compliance

**Problem:** External APIs have rate limits. Exceeding them results in 429 errors or bans.

**Pattern:**
1. Track remaining rate limit budget from response headers (if the API provides them)
2. If headers not available: maintain an internal rate limit counter
3. Before each request: check budget. If budget < minimum threshold, wait until reset window
4. On 429 response: back off for the retry-after duration from the response header, or default 60 seconds if not provided
5. Log every rate limit delay: these are signals that polling frequency needs adjustment

**Anti-pattern to avoid:** Implementing retry logic that immediately retries on 429. This burns through the rate limit faster and may result in being banned.

---

## Pattern 6: Source Adapter Interface

**Problem:** Each source has different APIs, formats, and behaviors. The rest of the system should not know these details.

**Standard interface every source adapter must implement:**

```python
class SourceAdapter:
    def fetch(self) -> list[RawRecord]:
        """Fetch latest records from this source. Returns empty list on failure."""
        ...
    
    def is_healthy(self) -> bool:
        """Returns True if the source is currently reachable."""
        ...
    
    def get_source_meta(self) -> SourceMeta:
        """Returns source name, type, and last successful fetch time."""
        ...
```

Adapters may also implement streaming methods if the source supports it. The polling interface above is the minimum requirement.

**Key design:** `fetch()` never raises an exception to the caller on source failures. It handles errors internally, logs them, and returns an empty list. The caller is responsible for detecting empty lists and acting accordingly (creating source gap records, etc.).

---

## Pattern 7: Normalization Pipeline

**Problem:** Raw records from different sources have wildly different formats. Downstream code should never deal with raw source formats.

**Pattern:**
1. Each source adapter produces raw records in the source's native format
2. Each source has a corresponding normalizer that transforms raw → canonical
3. Canonical records are validated before being passed to storage
4. The normalizer is the only code that knows the raw source format

**Separation:** Adapters handle connection and fetching. Normalizers handle transformation. These should be separate code units, not combined.

**Testing:** Every normalizer must have tests against representative raw source responses, including malformed inputs.

---

## Pattern 8: Batch Processing with Progress Tracking

**Problem:** Initial ingestion or catch-up after a gap may require processing large batches of historical records.

**Pattern:**
1. Process in small batches (configurable size; default: 50 records per batch)
2. After each batch: commit progress to storage (record the last processed timestamp/cursor)
3. If interrupted: resume from the last committed checkpoint, not from the start
4. Log batch progress: "processed batch 1/N, X records"

**Key requirement:** Batches are atomic: either all records in a batch are committed, or none are. Partial batch commits create inconsistent state.
