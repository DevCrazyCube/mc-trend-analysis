# System Architecture

## Overview

The system is structured as a sequence of loosely coupled pipelines that transform raw external data into scored, typed alerts. Each pipeline has a clear input contract, output contract, and failure behavior.

The architecture is designed to be implementation-agnostic. Specific tools, libraries, and services are documented in `docs/implementation/current-approach.md` and are explicitly subject to change. The structure described here is stable.

---

## Top-Level Subsystems

```
┌─────────────────────────────────────────────────────────────────────┐
│                         INGESTION LAYER                             │
│  Token Sources │ Event/News Sources │ Social Sources │ Chain Data   │
└────────────────────────────┬────────────────────────────────────────┘
                             │ normalized records
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       CORRELATION ENGINE                            │
│  Token ←→ Narrative linking │ Entity resolution │ Deduplication     │
└────────────────────────────┬────────────────────────────────────────┘
                             │ linked token-event pairs
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        SCORING ENGINE                               │
│  Narrative │ Authenticity │ Rug Risk │ Momentum │ Attention │ Timing│
└────────────────────────────┬────────────────────────────────────────┘
                             │ dimension scores + derived probabilities
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         ALERT ENGINE                                │
│  Classification │ Lifecycle management │ Expiry │ Re-evaluation     │
└────────────────────────────┬────────────────────────────────────────┘
                             │ typed alerts
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      DELIVERY LAYER                                 │
│  Channel routing │ Rate limiting │ Formatting │ Deduplication       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Subsystem Responsibilities

### Ingestion Layer

Connects to external data sources and produces normalized records. Does not score, rank, or interpret data. Only normalizes, timestamps, and stores.

Inputs: raw API responses, webhooks, streaming data, web scrapes
Outputs: normalized `TokenRecord`, `EventRecord`, `SocialRecord`, `ChainRecord`

Failure behavior: If a source is unavailable, produce a `source_gap` record for that source/timewindow. Downstream components handle missing data explicitly.

See: `docs/ingestion/`

---

### Correlation Engine

Matches tokens to events and narratives. The hardest problem in the system. Takes normalized records from the ingestion layer and produces `TokenNarrativeLink` records.

Inputs: normalized token records + event/social records
Outputs: `TokenNarrativeLink` (token_id, narrative_id, match_confidence, match_signals[])

Key functions:
- Name/symbol matching against trending terms
- Semantic matching (when deterministic matching fails)
- Deduplication: same token seen from multiple sources → one record
- OG resolution: multiple tokens matching same narrative → scored ranking

See: `docs/intelligence/narrative-linking.md`, `docs/intelligence/og-token-resolution.md`, `docs/skills/entity-resolution.md`

---

### Scoring Engine

Takes a `TokenNarrativeLink` and computes all six dimension scores plus derived probability values.

Inputs: `TokenNarrativeLink` + raw dimension data (chain data, social data, news data)
Outputs: `ScoredToken` record with all dimension scores, derived probabilities, and confidence

Scoring is deterministic for each dimension. Dimension weights are configurable parameters, not hardcoded values. LLM assistance is allowed only for specific sub-problems (e.g., semantic narrative match) and only if the output is validated and logged.

See: `docs/intelligence/scoring-model.md`, `docs/intelligence/probability-framework.md`

---

### Alert Engine

Takes a `ScoredToken` and classifies it into an alert type, manages the alert lifecycle, and decides when to re-evaluate.

Inputs: `ScoredToken`
Outputs: `Alert` records with type, reasoning, risk flags, confidence, expiry

The Alert Engine does not fetch new data. It only classifies and manages state based on what the Scoring Engine produced.

See: `docs/alerting/alert-engine.md`, `docs/alerting/alert-types.md`

---

### Delivery Layer

Takes `Alert` records and routes them to configured output channels. Applies rate limiting, formatting, and deduplication to prevent spam.

Inputs: `Alert` records
Outputs: formatted messages delivered to channels

Does not modify alerts. Only formats and delivers.

See: `docs/alerting/notification-strategy.md`

---

## Data Flow Summary

```
External Sources
    │
    ▼ (adapter per source)
Normalized Records (token, event, social, chain)
    │
    ▼ (correlation engine)
TokenNarrativeLink records
    │
    ▼ (scoring engine)
ScoredToken records
    │
    ▼ (alert engine)
Alert records (typed, with reasoning)
    │
    ▼ (delivery layer)
Output channels
```

---

## State and Storage

The system requires persistent state for:

- Token registry (all seen tokens)
- Narrative/event registry (all detected narratives)
- Alert registry (all active and historical alerts)
- Source gap log (track when sources were unavailable)
- Scoring history (for re-evaluation and calibration)

Storage technology is not prescribed here. See `docs/implementation/data-model.md` for the logical data model.

---

## Coupling Rules

1. **No upward coupling.** Ingestion does not know about scoring. Scoring does not know about alerts.
2. **Explicit contracts.** Each subsystem boundary has a defined record schema. Changes to that schema require updating the doc.
3. **No shared mutable state across subsystems.** Subsystems communicate through records, not shared objects.
4. **Failure isolation.** A failed ingestion source does not block the scoring pipeline. Missing data is surfaced as a data quality signal, not a crash.

---

## Scalability Assumptions

This is not designed for massive horizontal scale initially. Pump.fun launches thousands of tokens per day. The system must process all of them but does not need to handle millions of concurrent users or sub-millisecond latency.

Initial design targets:
- Process all new Pump.fun tokens within minutes of launch
- Evaluate all six scoring dimensions within 5 minutes of a token being correlated to a narrative
- Deliver alerts within 10 minutes of scoring completion

Scaling bottlenecks will emerge empirically. Do not optimize prematurely.
