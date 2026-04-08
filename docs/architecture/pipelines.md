# Pipelines

This document defines each named pipeline: its trigger, inputs, outputs, and failure modes.

A "pipeline" here is a logical processing path, not necessarily a specific technical implementation (queue, stream, batch job, etc.). Implementation choices are in `docs/implementation/current-approach.md`.

---

## Pipeline 1: Token Ingestion Pipeline

**Trigger:** Continuous polling or event-driven webhook from token launch source

**Input:** Raw token launch event from Pump.fun or equivalent source

**Processing steps:**
1. Parse raw event into candidate `TokenRecord`
2. Validate minimum required fields (address, name, launch time)
3. Fetch supplementary chain data (deployer address, initial liquidity, initial holder count)
4. Normalize to canonical schema
5. Deduplicate against token registry (same address seen from multiple sources)
6. Write to token registry with status: `new`

**Output:** `TokenRecord` with status `new` in token registry

**Failure modes:**
- Source unavailable: log `source_gap`, continue. No token data is not the same as no tokens launched.
- Invalid record: log parse error, discard record, do not crash pipeline
- Duplicate: update existing record with freshest data, do not create duplicate

**Latency target:** Token registered within 2 minutes of launch

---

## Pipeline 2: Event / Narrative Ingestion Pipeline

**Trigger:** Continuous polling of news, social, and search trend sources (cadence varies by source)

**Input:** Raw signals from news APIs, social platforms, search trend APIs

**Processing steps:**
1. Fetch raw data from each source adapter
2. Parse into candidate `EventRecord` or `SocialRecord`
3. Extract key terms, entities, topics
4. Score source reliability
5. Deduplicate: same story from multiple sources → single `EventRecord` with multiple source references
6. Normalize to canonical schema
7. Write to event/narrative registry with status: `active`

**Output:** `EventRecord` or `SocialRecord` in event registry

**Failure modes:**
- Source unavailable: log gap. Some sources going down should not halt event ingestion from other sources.
- Ambiguous entity extraction: store raw terms, mark extraction confidence as low
- Duplicate event from same source: update existing, do not duplicate

**Cadence targets:**
- Search trends: every 15–30 minutes
- News: every 5–10 minutes
- Social: every 2–5 minutes (or streaming where available)

---

## Pipeline 3: Correlation Pipeline

**Trigger:** New `TokenRecord` added to registry, OR new/updated `EventRecord` that matches existing tokens

**Input:** `TokenRecord` + current `EventRecord` / `SocialRecord` set

**Processing steps:**
1. Extract token name, symbol, description terms
2. Match against active narrative set (exact match first, then fuzzy/semantic match)
3. Score match confidence for each candidate narrative
4. If confidence above minimum threshold: create `TokenNarrativeLink`
5. If multiple tokens match same narrative: queue for OG resolution
6. If no narrative match: mark token as `unlinked`, low priority

**Output:** `TokenNarrativeLink` records for tokens with sufficient narrative match

**Failure modes:**
- No narrative match found: not a failure — token marked as `unlinked`, no alert generated
- Ambiguous match (multiple narratives equally plausible): create links to all candidates with low confidence, flag for review
- LLM-assisted match fails: fall back to deterministic term matching, log fallback

---

## Pipeline 4: Scoring Pipeline

**Trigger:** New or updated `TokenNarrativeLink` record

**Input:** `TokenNarrativeLink` + chain data + social data + rug risk data

**Processing steps:**
1. Compute narrative relevance score (from link confidence + narrative strength)
2. Compute authenticity / OG score
3. Compute rug risk score
4. Compute momentum quality score
5. Compute attention strength score
6. Compute timing quality score
7. Combine dimensions into `P_potential`, `P_failure`, `net_potential`
8. Compute `confidence_score` based on data completeness
9. Write `ScoredToken` record

**Output:** `ScoredToken` record with all scores and derived probabilities

**Failure modes:**
- Missing dimension data: use default pessimistic value for that dimension, reduce confidence score, log gap
- Scoring function error: log error, mark token as `scoring_failed`, alert operator, do not output partial score
- Stale data detected: flag `data_freshness: stale` on output, reduce confidence

**Latency target:** Score produced within 5 minutes of `TokenNarrativeLink` creation

---

## Pipeline 5: Alert Classification Pipeline

**Trigger:** New or updated `ScoredToken` record

**Input:** `ScoredToken` record

**Processing steps:**
1. Apply classification thresholds to `net_potential` and `P_failure` (see `docs/alerting/alert-types.md`)
2. Determine alert type
3. Compose reasoning summary from dimension scores
4. Set expiry time and re-evaluation trigger
5. Check for existing alert for this token:
   - If new: create alert
   - If existing and type changed: update alert, log state transition
   - If existing and type unchanged: update score data, do not re-alert unless significant change
6. Write `Alert` record

**Output:** `Alert` record with type, reasoning, expiry

**Failure modes:**
- Classification threshold ambiguous (score at exact boundary): round down (more conservative classification)
- No change in alert type: silent update, no new delivery
- Alert creation error: log, do not discard scored token — retry

---

## Pipeline 6: Alert Expiry / Re-evaluation Pipeline

**Trigger:** Time-based (scheduled) OR event-triggered (significant new signal for an active token)

**Input:** Active `Alert` records past their expiry time, OR significant new data for an active token

**Processing steps:**
1. For time-expired alerts: fetch fresh data, re-run scoring pipeline, re-classify
2. For event-triggered re-evaluation: fetch new signal data, re-run only affected dimensions, re-classify
3. If alert type changes: emit updated alert
4. If token no longer meets minimum threshold: retire alert, log retirement reason

**Output:** Updated or retired `Alert` records

**Trigger thresholds for event-based re-evaluation:**
- Liquidity drops > 30% in < 1 hour → immediate re-evaluation
- Holder count drops > 20% in < 30 minutes → immediate re-evaluation
- Source narrative goes cold (attention drops > 50%) → re-evaluation within 15 minutes
- Deployer flagged by external signal → immediate re-evaluation

---

## Pipeline 7: Delivery Pipeline

**Trigger:** New or updated `Alert` record (for new/upgraded alerts only)

**Input:** `Alert` record

**Processing steps:**
1. Check if alert warrants delivery (type threshold, not all types are delivered — see `docs/alerting/notification-strategy.md`)
2. Check rate limit: avoid delivering more than N alerts per time window per channel
3. Format alert for each target channel
4. Deliver to channels
5. Log delivery status

**Output:** Delivered message to channel(s), delivery log entry

**Failure modes:**
- Channel unavailable: queue for retry with exponential backoff
- Rate limit exceeded: hold lower-priority alerts, deliver high-priority immediately
- Formatting error: log, deliver with minimal formatting rather than failing silently

---

## Pipeline Dependency Map

```
Token Ingestion ──────────────────────────────────┐
                                                   │
Event Ingestion ──────────────────────────────────┤
                                                   ▼
                                         Correlation Pipeline
                                                   │
                                                   ▼
                                          Scoring Pipeline
                                                   │
                                                   ▼
                                    Alert Classification Pipeline
                                                   │
                                    ┌──────────────┤
                                    │              │
                             Delivery Pipeline    Expiry / Re-evaluation Pipeline
                                                   │
                                                   └──── back to Scoring Pipeline
```

The expiry/re-evaluation pipeline creates a feedback loop. This is intentional: alert quality must degrade gracefully as narratives age.
