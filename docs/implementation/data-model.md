# Data Model

This document defines the core entities, their relationships, and their lifecycle states. This is the logical data model — not a database schema.

Physical storage implementation is in `docs/implementation/current-approach.md`.

---

## Core Entities

### Entity: Token

A token observed in the system. One token corresponds to one deployed contract address on Solana.

```
Token
  token_id: uuid (PK)
  address: string (unique, Solana address)
  name: string
  symbol: string
  description: string?
  deployed_by: string (wallet address)
  launch_time: datetime
  launch_platform: string
  status: TokenStatus
  created_at: datetime
  updated_at: datetime
```

**TokenStatus enum:** `new | linked | scored | alerted | expired | discarded`

**Relationships:**
- One Token → many TokenChainSnapshots (time series of chain state)
- One Token → many TokenNarrativeLinks
- One Token → many Alerts

---

### Entity: TokenChainSnapshot

A point-in-time snapshot of on-chain state for a token. Multiple snapshots per token, taken over time.

```
TokenChainSnapshot
  snapshot_id: uuid (PK)
  token_id: uuid (FK → Token)
  sampled_at: datetime
  
  holder_count: int?
  top_5_holder_pct: float?
  top_10_holder_pct: float?
  new_wallet_holder_pct: float?
  
  liquidity_usd: float?
  liquidity_locked: bool?
  liquidity_lock_hours: int?
  liquidity_provider_count: int?
  
  volume_1h_usd: float?
  volume_24h_usd: float?
  trade_count_1h: int?
  unique_traders_1h: int?
  
  deployer_known_bad: bool
  deployer_prior_deployments: int?
  
  data_source: string
  data_gaps: string[]
```

---

### Entity: Narrative

A detected real-world trend or event. A narrative can link to many tokens.

```
Narrative
  narrative_id: uuid (PK)
  anchor_terms: string[]
  related_terms: string[]
  entities: json  // [{ name, type, confidence }]
  description: string
  
  attention_score: float
  narrative_velocity: float
  source_type_count: int
  
  state: NarrativeState
  first_detected: datetime
  peaked_at: datetime?
  dead_at: datetime?
  updated_at: datetime
  
  extraction_confidence: float
  ambiguous: bool
```

**NarrativeState enum:** `EMERGING | PEAKING | DECLINING | DEAD`

**Relationships:**
- One Narrative → many NarrativeSources
- One Narrative → many TokenNarrativeLinks

---

### Entity: NarrativeSource

A single source record contributing to a narrative's evidence base.

```
NarrativeSource
  source_id: uuid (PK)
  narrative_id: uuid (FK → Narrative)
  source_type: string
  source_name: string
  signal_strength: float
  first_seen: datetime
  last_updated: datetime
  raw_reference: string?
```

---

### Entity: TokenNarrativeLink

The connection between a token and a narrative. This is the unit that triggers scoring.

```
TokenNarrativeLink
  link_id: uuid (PK)
  token_id: uuid (FK → Token)
  narrative_id: uuid (FK → Narrative)
  
  match_confidence: float
  match_method: string  // "exact" | "abbreviation" | "related" | "semantic"
  match_signals: string[]
  
  og_rank: int?  // 1 = most likely OG in this namespace; null if only token
  og_score: float?
  og_signals: json?
  
  created_at: datetime
  updated_at: datetime
  
  status: "active" | "superseded" | "retired"
```

**Relationships:**
- One TokenNarrativeLink → many ScoredTokens (one per scoring run)
- One TokenNarrativeLink → many Alerts

---

### Entity: ScoredToken

A complete scoring result for a token-narrative link at a point in time.

```
ScoredToken
  score_id: uuid (PK)
  link_id: uuid (FK → TokenNarrativeLink)
  token_id: uuid (FK → Token)
  narrative_id: uuid (FK → Narrative)
  scored_at: datetime
  
  // Dimension scores
  narrative_relevance: float
  og_score: float
  rug_risk: float
  momentum_quality: float
  attention_strength: float
  timing_quality: float
  
  // Derived probabilities
  p_potential: float
  p_failure: float
  net_potential: float
  confidence_score: float
  
  // Supporting data
  risk_flags: string[]
  data_gaps: string[]
  dimension_details: json  // full dimension calculation detail for audit
  
  // Data freshness
  chain_data_age_minutes: int?
  social_data_age_minutes: int?
  narrative_data_age_minutes: int?
  data_freshness_status: "fresh" | "stale" | "missing"
```

---

### Entity: Alert

A user-facing output representing a classified opportunity or risk signal.

```
Alert
  alert_id: uuid (PK)
  token_id: uuid (FK → Token)
  link_id: uuid (FK → TokenNarrativeLink)
  score_id: uuid (FK → ScoredToken)  // most recent scoring used
  
  alert_type: AlertType
  
  net_potential: float
  p_potential: float
  p_failure: float
  confidence_score: float
  
  risk_flags: string[]
  reasoning: string
  
  status: AlertStatus
  created_at: datetime
  updated_at: datetime
  expires_at: datetime
  retired_at: datetime?
  retirement_reason: string?
  
  re_eval_triggers: string[]
  
  history: json  // [ { timestamp, previous_type, previous_net_potential, change_reason } ]
```

**AlertType enum:** `possible-entry | high-potential-watch | take-profit-watch | verify | watch | exit-risk | discard`

**AlertStatus enum:** `ACTIVE | RETIRED`

---

### Entity: AlertDelivery

A log of every delivery attempt for an alert.

```
AlertDelivery
  delivery_id: uuid (PK)
  alert_id: uuid (FK → Alert)
  channel_type: string
  channel_id: string
  attempted_at: datetime
  status: "delivered" | "failed" | "rate_limited" | "skipped"
  failure_reason: string?
```

---

### Entity: RejectedCandidate

A diagnostic record capturing the most recent scoring result for a token-narrative pair that was classified as "ignore" (i.e., failed to produce any alert).  Used by the operator dashboard to understand why tokens are not alerting, and to tune thresholds.

**Primary key:** `(token_id, narrative_id)` — compound key.  Each re-score replaces the previous row via INSERT OR REPLACE.  There is at most one row per token-narrative pair at any time.

```
RejectedCandidate
  token_id: uuid (FK → Token)
  narrative_id: uuid (FK → Narrative)
  token_name: string
  token_symbol: string
  narrative_name: string
  score_id: uuid (FK → ScoredToken)
  alert_type: "ignore"
  net_potential: float
  p_potential: float
  p_failure: float
  confidence_score: float
  watch_gap: float          — watch_min_net_potential - net_potential (positive = below threshold)
  rejection_reasons: list[RejectionReason]
  dimension_scores: dict
  risk_flags: list[string]
  data_gaps: list[string]
  rejected_at: datetime
```

**RejectionReason structure:**
```
  code: string              — machine-readable (e.g., "net_potential_below_watch")
  tier: string              — alert tier this reason blocked
  actual: float | string    — the actual value
  threshold: float | string — the required threshold
  gap: float | null         — distance from meeting the condition (positive = needs to increase)
```

**Known reason codes:**

| code | tier | meaning |
|---|---|---|
| `net_potential_below_watch` | watch | net_potential < 0.25 |
| `net_potential_below_verify` | verify | net_potential < 0.35 |
| `net_potential_below_hpw` | high_potential_watch | net_potential < 0.45 |
| `net_potential_below_pe` | possible_entry | net_potential < 0.60 |
| `p_failure_too_high_for_hpw` | high_potential_watch | p_failure >= 0.50 |
| `p_failure_too_high_for_pe` | possible_entry | p_failure >= 0.30 |
| `confidence_below_hpw_floor` | high_potential_watch | confidence < 0.55 |
| `confidence_below_pe_floor` | possible_entry | confidence < 0.65 |
| `narrative_state_not_active` | high_potential_watch\|possible_entry | narrative not EMERGING or PEAKING |
| `blocking_flag_caps_at_verify` | possible_entry\|high_potential_watch | critical risk flag present |
| `discard_flag_active` | all | known-bad deployer or equivalent |
| `missing_required_enrichment` | rug_risk_dimension | specific chain data gap (holder_concentration, liquidity_data, etc.) |

**Retention:** 48 hours (pruned each pipeline cycle).  This is diagnostic data, not calibration data.

**API:** `GET /api/candidates?limit=N` — returns rows sorted by `watch_gap ASC` (closest to alert threshold first).

---

### Entity: SourceGap

A log entry recording when a data source was unavailable.

```
SourceGap
  gap_id: uuid (PK)
  source_type: string
  source_name: string
  started_at: datetime
  ended_at: datetime?
  affected_records: int?
  notes: string?
```

---

## Entity Relationships Overview

```
Narrative ──────────────────────── NarrativeSource (many)
     │
     │ (via TokenNarrativeLink)
     │
Token ──────────────── TokenChainSnapshot (many, time series)
  │
  └── TokenNarrativeLink ─────── ScoredToken (many, one per scoring run)
            │                             │
            │                             └── RejectedCandidate (one, most recent ignore)
            └── Alert ─────────── AlertDelivery (many)
```

---

## Key Design Decisions

**Immutable scoring history:** ScoredToken records are never overwritten. Each scoring run creates a new ScoredToken record. This preserves the full scoring history for calibration analysis.

**Alert history in JSON:** Alert history is stored as a JSON array on the Alert record rather than a separate entity. This simplifies queries for the common case (show current alert with context) while preserving the history.

**Nullable dimension scores:** All dimension scores and probability values are nullable on the ScoredToken record. A null value means "could not be computed" and corresponds to a `DATA_GAP` flag. Not-null means a value was actually computed (even if from a conservative default).

**No hard deletes:** Nothing is deleted. Tokens, narratives, links, and alerts are retired/marked-dead, not deleted. This is required for calibration data and audit purposes.

---

## Data Retention

| Entity | Retention Policy |
|---|---|
| Token | Indefinite (status = expired after 30 days of inactivity) |
| TokenChainSnapshot | 90 days (aggregate older data) |
| Narrative | Indefinite (status = DEAD, never deleted) |
| ScoredToken | Indefinite (calibration data) |
| Alert | Indefinite (calibration data) |
| AlertDelivery | 90 days |
| SourceGap | 90 days |
| RejectedCandidate | 48 hours (diagnostic data only; compound PK keeps one row per token-narrative pair) |

Retention policies are initial defaults and should be revisited as storage costs grow.
