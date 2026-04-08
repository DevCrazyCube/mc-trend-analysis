# Event Flow

This document traces how a specific real-world scenario moves through the system end to end. Understanding the event flow is essential for debugging, extending, and validating the system.

---

## Primary Event Flow: New Token with Narrative Match

This is the most important flow — a new token is launched that connects to an active real-world trend.

### Step 1: Narrative Detected

**Actor:** Event Ingestion Pipeline

A news article is published, or a search trend spikes, or a social topic goes viral. The event ingestion pipeline detects this via one or more source adapters.

Example: A major AI company announces a product. The term "DeepMind" starts trending.

**Record created:** `EventRecord { narrative_id: "deepmind-product-launch-2024-10", terms: ["deepmind", "google ai", "gemini ultra"], attention_score: 0.84, sources: ["google-trends", "twitter", "coindesk"], created_at: T+0 }`

---

### Step 2: Token Launched

**Actor:** Token Ingestion Pipeline

Within minutes of the news, multiple tokens are launched on Pump.fun with names like "DEEPMIND", "DMIND", "DEEP-AI".

**Records created:** Three `TokenRecord` entries, each with address, name, deployer, launch_time, initial_liquidity.

---

### Step 3: Correlation

**Actor:** Correlation Engine

The correlation engine runs matching between new `TokenRecord` entries and active `EventRecord` entries.

- `DEEPMIND` → exact term match on "deepmind" → match_confidence: 0.97
- `DMIND` → partial match on "deepmind" abbreviation → match_confidence: 0.61
- `DEEP-AI` → term overlap on "deep" + "ai" → match_confidence: 0.54

Three `TokenNarrativeLink` records are created, all linked to narrative `deepmind-product-launch-2024-10`.

---

### Step 4: OG Resolution

**Actor:** OG Resolver (triggered because multiple tokens linked to same narrative)

OG Resolver receives all three linked tokens and evaluates:

| Token | Launch Time | Name Match Score | Cross-source Mentions | OG Rank |
|---|---|---|---|---|
| DEEPMIND | T+3 min | 0.98 | 2 sources | 1 |
| DMIND | T+7 min | 0.63 | 0 sources | 2 |
| DEEP-AI | T+12 min | 0.54 | 0 sources | 3 |

Result: `DEEPMIND` is most likely OG. `DMIND` and `DEEP-AI` are likely copycats. All three continue through scoring — only OG rank changes.

---

### Step 5: Dimension Scoring

**Actor:** Scoring Engine (runs for each of the three tokens in parallel)

For `DEEPMIND (DEEPMIND)`:

| Dimension | Raw Score | Notes |
|---|---|---|
| Narrative Relevance | 0.91 | High-confidence narrative link, strong source corroboration |
| Authenticity (OG) | 0.87 | First mover, high name match, cross-source mentions |
| Rug Risk | 0.38 (risk) | New deployer, 3 wallets hold 62% of supply — medium-high risk |
| Momentum Quality | 0.71 | Growing holder count, volume is partially organic |
| Attention Strength | 0.84 | Narrative has strong multi-source support |
| Timing Quality | 0.79 | Early in narrative lifecycle, ~15 min since narrative detected |

---

### Step 6: Probability Calculation

**Actor:** Scoring Aggregator

Using the formulas from `docs/intelligence/probability-framework.md`:

```
P_potential = weighted(narrative=0.91, og=0.87, momentum=0.71, attention=0.84, timing=0.79)
            = 0.83

P_failure = weighted(rug_risk=0.38, fakeout_risk=low, liquidity=medium)
          = 0.31

net_potential = P_potential * (1 - P_failure)
              = 0.83 * 0.69
              = 0.57

confidence_score = 0.74 (some chain data estimated, social sources partially available)
```

---

### Step 7: Alert Classification

**Actor:** Alert Classifier

`net_potential = 0.57`, `P_failure = 0.31`, `confidence = 0.74`

Threshold check against `docs/alerting/alert-types.md`:
- net_potential 0.57 with confidence 0.74 → `high-potential watch`

---

### Step 8: Alert Creation

**Actor:** Alert Registry

Alert created:
```json
{
  "type": "high-potential watch",
  "token": "DEEPMIND",
  "address": "...",
  "narrative": "deepmind-product-launch-2024-10",
  "net_potential": 0.57,
  "P_failure": 0.31,
  "confidence": 0.74,
  "risk_flags": ["high_holder_concentration", "new_deployer"],
  "reasoning": "Strong narrative match to trending DeepMind product launch. First mover token with cross-source name presence. Medium-high rug risk due to holder concentration and unknown deployer. Opportunity window likely 2–6 hours based on narrative velocity.",
  "expiry": "T+2h",
  "re_eval_triggers": ["liquidity_drop_30pct", "attention_decay_50pct"]
}
```

---

### Step 9: Delivery

**Actor:** Delivery Router

Alert formatted and delivered to configured channels. Rate limit checked. Delivery logged.

---

### Step 10: Re-evaluation Loop

**Actor:** Re-evaluation Scheduler

At `T+2h`, expiry triggers re-evaluation. Fresh chain data shows:
- Holder concentration reduced to 48% (positive)
- Narrative attention down to 0.51 from 0.84 (negative)
- Token still active, volume sustained

Re-scored. `net_potential` recalculated. If classification unchanged, no re-delivery. If degraded to `watch`, alert updated silently. If degraded to `exit-risk`, re-delivered to channels.

---

## Secondary Flow: Token with No Narrative Match

**Step 1:** Token ingested
**Step 2:** Correlation engine finds no matching narrative above threshold
**Step 3:** Token marked `unlinked` in registry
**Step 4:** No scoring, no alert generated
**Step 5:** Token re-evaluated automatically on next event ingestion cycle if new narratives emerge that match

---

## Secondary Flow: Rug Detected Mid-Alert Lifecycle

**Step 1:** Token has active `high-potential watch` alert
**Step 2:** Ingestion picks up on-chain event: deployer wallet removes 90% of liquidity
**Step 3:** Re-evaluation triggered immediately (liquidity_drop_30pct trigger fired)
**Step 4:** Rug risk score updated to 0.91 (critical)
**Step 5:** `P_failure` recalculated to 0.88
**Step 6:** `net_potential` collapses to 0.09
**Step 7:** Alert reclassified to `exit-risk`
**Step 8:** Immediate re-delivery with prominent risk flags
**Step 9:** Original `high-potential watch` alert retired with state transition logged

---

## Failure Flow: Source Unavailable

**Step 1:** Social source adapter returns error
**Step 2:** `source_gap` record logged for that source and time window
**Step 3:** Tokens being scored with missing social data: `attention_score` computed from remaining sources only
**Step 4:** `confidence_score` reduced proportionally
**Step 5:** Alert still generated but with `data_gap_flags: ["social_source_unavailable"]`
**Step 6:** User sees reduced confidence in alert output — context is preserved

---

## Flow Timing Summary

| Stage | Target Latency |
|---|---|
| Token launch → TokenRecord | < 2 min |
| EventRecord created → available to correlator | < 5 min |
| TokenRecord + EventRecord → TokenNarrativeLink | < 3 min |
| TokenNarrativeLink → ScoredToken | < 5 min |
| ScoredToken → Alert | < 1 min |
| Alert → Delivered | < 2 min |
| **Total: launch to alert** | **< 13 min target** |

Re-evaluation on event trigger (rug signal, attention decay): target < 5 min end to end.
