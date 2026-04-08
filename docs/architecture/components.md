# Components

This document defines each logical component in the system: its single responsibility, its interface contract, and what it must not do.

Components are logical units. They may be implemented as modules, classes, services, or functions. What matters is that the responsibility boundary is respected, not the packaging.

---

## Component: Source Adapter

**Responsibility:** Connect to a single external data source and produce normalized records.

**Input:** Configuration (endpoint, credentials, polling interval)
**Output:** Stream or batch of raw records in the source's native format

**Must do:**
- Handle connection errors gracefully (retry with backoff, log failures)
- Emit a `source_gap` record when data cannot be fetched
- Timestamp every record with both fetch time and claimed source time

**Must not do:**
- Interpret or score the data
- Make decisions about relevance
- Interact with any other component directly

**One adapter per source.** Do not create a generic "all sources" adapter. The impedance mismatch between sources is real and must be handled per-source.

---

## Component: Record Normalizer

**Responsibility:** Transform source-specific raw records into canonical `TokenRecord`, `EventRecord`, `SocialRecord`, or `ChainRecord` format.

**Input:** Raw record from a Source Adapter
**Output:** Canonical normalized record

**Must do:**
- Map all required fields to canonical schema fields
- Flag optional fields as missing when not available
- Validate field types and ranges
- Log normalization failures with sufficient detail to debug

**Must not do:**
- Enrich data (look up additional context)
- Make relevance judgments
- Cross-reference other records

---

## Component: Token Registry

**Responsibility:** Persistent store of all seen tokens.

**Interface:**
- `register(TokenRecord) → token_id` — add or update
- `lookup(address) → TokenRecord | None`
- `list(status, since) → [TokenRecord]`

**Must do:**
- Deduplicate by contract address
- Track first_seen and last_updated timestamps
- Store status transitions (new → linked → scored → alerted → retired)

**Must not do:**
- Compute scores
- Make alert decisions

---

## Component: Narrative Registry

**Responsibility:** Persistent store of active narratives and events.

**Interface:**
- `register(EventRecord) → narrative_id`
- `lookup(term) → [Narrative]` — search by keyword or entity
- `get_active(since) → [Narrative]`
- `mark_decayed(narrative_id, reason)`

**Must do:**
- Track narrative freshness (when was it last seen in live sources)
- Support multi-term queries for narrative matching
- Allow a narrative to reference multiple source events

---

## Component: Correlation Engine

**Responsibility:** Match tokens to narratives and produce `TokenNarrativeLink` records.

**Input:** `TokenRecord`, active `Narrative` set
**Output:** `TokenNarrativeLink` (token_id, narrative_id, match_confidence, match_signals[])

**Must do:**
- Apply deterministic matching first (exact and near-exact term match)
- Apply semantic/fuzzy matching only when deterministic fails
- Produce match_signals list explaining why the match was made
- Handle ambiguous matches by creating multiple links with low confidence

**Must not do:**
- Fetch external data
- Score tokens beyond the match confidence
- Access alert state

---

## Component: OG Resolver

**Responsibility:** When multiple tokens match the same narrative, rank them by authenticity likelihood.

**Input:** List of `TokenNarrativeLink` records for the same narrative
**Output:** Each link annotated with `og_rank` (1 = most likely OG) and `og_signals[]`

**Must do:**
- Apply timing signals (earliest launched relative to narrative)
- Apply name alignment signals (how closely does the name match the canonical narrative term)
- Apply cross-source validation signals (is this token mentioned in multiple independent sources)
- Produce explicit reasoning for each ranking decision

**Must not do:**
- Make a binary OG/fake decision — produce ranked likelihood only
- Discard tokens — all candidates pass through with their ranking

---

## Component: Rug Risk Analyzer

**Responsibility:** Evaluate structural and behavioral risk signals for a single token.

**Input:** `TokenRecord` + chain data (deployer history, holder distribution, liquidity data)
**Output:** `RugRiskResult` (overall_risk_score, risk_tier, risk_signals[])

**Must do:**
- Evaluate each risk category independently (deployer, concentration, liquidity, metadata)
- Produce a list of specific risk signals that contributed to the score
- Apply a conservative default when data is missing (missing = higher risk)
- Include explicit uncertainty statements when signals are ambiguous

**Must not do:**
- Claim a token is "safe"
- Override risk signals based on narrative quality (a great story doesn't reduce rug risk)

---

## Component: Momentum Analyzer

**Responsibility:** Evaluate whether price and volume momentum is organic or manipulated.

**Input:** On-chain trading data (volume, trades, holder changes over time), social signal data
**Output:** `MomentumResult` (momentum_score, momentum_type, signals[])

**Must do:**
- Distinguish volume spike from organic growth
- Detect wash trade patterns
- Cross-reference on-chain movement with social signal presence
- Score momentum quality, not just momentum magnitude

**Must not do:**
- Predict future price movement
- Incorporate narrative quality (momentum is a separate dimension)

---

## Component: Attention Analyzer

**Responsibility:** Measure the strength of external attention on the narrative linked to a token.

**Input:** `EventRecord` and `SocialRecord` data for a given narrative
**Output:** `AttentionResult` (attention_score, attention_signals[], narrative_velocity)

**Must do:**
- Aggregate attention across multiple sources
- Weight sources by reliability
- Measure velocity (is attention growing, stable, or declining?)
- Track recency (is this narrative fresh or decaying?)

**Must not do:**
- Conflate attention with authenticity (high attention doesn't mean safe token)
- Use attention from the token's own community as external attention evidence

---

## Component: Scoring Aggregator

**Responsibility:** Combine dimension scores into `P_potential`, `P_failure`, `net_potential`, and `confidence_score`.

**Input:** All dimension results (narrative, OG, rug risk, momentum, attention, timing)
**Output:** `ScoredToken` record

**Must do:**
- Apply defined weight formula from `docs/intelligence/probability-framework.md`
- Compute confidence based on data completeness
- Flag specific data gaps that reduced confidence
- Log all inputs and output for auditability

**Must not do:**
- Invent data for missing dimensions
- Apply ad-hoc adjustments outside the defined formula

---

## Component: Alert Classifier

**Responsibility:** Map a `ScoredToken` to an alert type using defined thresholds.

**Input:** `ScoredToken`
**Output:** `AlertClassification` (type, reasoning_summary, risk_flag_list)

**Must do:**
- Apply thresholds from `docs/alerting/alert-types.md`
- Produce human-readable reasoning summary that maps to specific score values
- Populate risk flag list from rug risk and other signals

**Must not do:**
- Fetch new data
- Override classification thresholds without explicit rule change
- Suppress alerts based on delivery preferences (that's the delivery layer's job)

---

## Component: Alert Registry

**Responsibility:** Persistent store of all alerts with their full history.

**Interface:**
- `create(Alert) → alert_id`
- `update(alert_id, updates)`
- `get_active() → [Alert]`
- `get_history(token_id) → [Alert]`
- `retire(alert_id, reason)`

**Must do:**
- Record every state transition with timestamp and reason
- Support querying by token, by type, by time window
- Never delete records (mark as retired, not deleted)

---

## Component: Delivery Router

**Responsibility:** Format and route alerts to configured output channels.

**Input:** `Alert` record, channel configuration
**Output:** Formatted message delivered to channel

**Must do:**
- Apply rate limiting per channel
- Format alerts according to channel requirements
- Log every delivery attempt and outcome
- Handle channel failures with retry

**Must not do:**
- Modify alert content or classification
- Make decisions about whether an alert is valid

---

## Component: Re-evaluation Scheduler

**Responsibility:** Trigger re-evaluation of active alerts when expiry or significant events occur.

**Input:** Active alert registry, incoming event stream
**Output:** Re-evaluation triggers to scoring pipeline

**Must do:**
- Track alert expiry times and trigger re-evaluation proactively
- Detect event types that should trigger immediate re-evaluation
- Log every re-evaluation trigger with reason

**Must not do:**
- Skip re-evaluation to improve performance
- Batch re-evaluations in ways that introduce unacceptable latency
