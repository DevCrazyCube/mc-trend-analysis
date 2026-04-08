# Success Metrics

This document defines how system quality is measured. Financial outcomes are not a valid primary metric. Signal quality is.

---

## Why Not Financial Outcomes as Primary Metric

Using price appreciation as the primary success metric introduces several problems:

1. **Survivor bias** — Tokens that moved but weren't alerted are invisible. Tokens that were alerted but did nothing are over-represented in failure analysis.
2. **Causation confusion** — The system doesn't cause price action. It detects conditions correlated with it.
3. **Timeframe sensitivity** — An alert that was "right" at T+2 hours and "wrong" at T+24 hours is ambiguous.
4. **Manipulation risk** — A high-quality alert on a successfully manipulated token looks like a success when it isn't.

We measure what the system can actually control: **the quality of its reasoning and the accuracy of its probability estimates over time.**

---

## Primary Metrics

### 1. Alert Calibration Rate

**Definition:** Across all alerts with a given `net_potential` range, what percentage resulted in a measurable opportunity window?

Example target (illustrative, not prescriptive):
- Alerts with `net_potential` 0.70–0.80 should see opportunity windows ~70% of the time
- A system that scores 0.75 but produces opportunity windows 90% of the time is overconfident the other direction — it may be underestimating failure

**How measured:** Compare predicted probability buckets to observed outcomes over rolling windows. Requires defining "opportunity window" clearly (see below).

**Opportunity window definition:** Token achieves at least 2x from alert price within 4 hours of alert, *and* a rational exit existed (liquidity, no rug event). This is a working definition and should be revised as data accumulates.

---

### 2. Rug / Failure Prediction Rate

**Definition:** Across tokens flagged with high `P_failure`, what percentage actually experienced a rug, liquidity removal, or rapid unrecoverable decline within 6 hours?

This is more measurable than upside because failure events are clearer.

**Target:** High-risk flags (`P_failure` > 0.70) should correspond to observable failure events at a rate significantly above base rate for all tokens.

---

### 3. OG Resolution Accuracy

**Definition:** Across tokens where the system identified a canonical/OG token in a namespace, what percentage of those assessments were confirmed by later evidence (social consensus, narrative alignment, timing)?

**How measured:** Manual review sample or downstream signal (e.g., which token in a cluster retains narrative relevance after 12 hours).

---

### 4. Narrative Relevance Decay Tracking

**Definition:** When the system assigns a narrative link, how long does that link remain valid based on external attention signals?

A narrative link that was scored 0.9 at T+0 but where the narrative collapsed by T+2 hours should trigger a re-evaluation, and the system should have detected the decay.

**Target:** Narrative decay should be flagged within 1–2 polling cycles of detectible signal drop.

---

### 5. False Positive Rate (Copycat Detection)

**Definition:** Among tokens identified as copycats, what percentage were actually copycats vs. independent launches that legitimately belonged to the same narrative?

False positives here mean legitimate tokens get suppressed. False negatives mean copycats get elevated.

**Target:** This is an open calibration question. Initially err toward flagging ambiguity rather than making confident OG/copycat decisions.

---

### 6. Alert Latency

**Definition:** Time from first on-chain evidence of a token being relevant to alert delivery.

This is a system performance metric. Narrative windows are short. A correct alert delivered 4 hours late is not useful.

**Target:** Under 10 minutes from token launch/event correlation to alert output for high-confidence signals. Under 30 minutes for signals that require cross-source validation.

---

### 7. Confidence Score Validity

**Definition:** Alerts with high confidence scores should have lower variance in outcomes than alerts with low confidence scores.

High confidence means "we have good evidence." It must correlate with prediction stability, not with prediction accuracy directly.

---

### 8. System Coverage (Recall)

**Definition:** Among tokens that would have qualified as high-potential by post-hoc analysis, what fraction did the system surface in time?

This requires periodic retrospective analysis. It prevents the system from optimizing purely for precision (low noise) at the cost of missing real signals.

---

## Secondary Metrics (Operational Health)

| Metric | Description |
|---|---|
| Ingestion latency | Time from source event to normalized record in system |
| Source availability | Uptime of each data source adapter |
| Scoring pipeline throughput | Tokens scored per minute |
| Alert queue depth | Backlog of unprocessed alerts |
| Data staleness rate | Percentage of active evaluations using data older than threshold |
| Re-evaluation trigger rate | How often expiry logic fires and re-scores a token |

---

## What We Do Not Measure

- Average profit per alert followed
- Win rate by number of trades
- Dollar returns from any strategy

These are beyond system scope and would introduce the wrong optimization pressure.

---

## Measurement Cadence

| Metric | Cadence |
|---|---|
| Alert calibration | Rolling 7-day and 30-day windows |
| Rug prediction rate | Rolling 7-day |
| OG resolution accuracy | Monthly manual sample review |
| Alert latency | Continuous (p50, p95 tracked) |
| Ingestion/operational | Continuous real-time monitoring |

---

## Open Questions

- **Opportunity window definition needs empirical tuning.** The 2x/4hr definition above is a starting assumption. Adjust based on actual data after first 30 days.
- **Calibration requires sufficient sample size.** Early system operation will not produce statistically meaningful calibration. Do not over-interpret early results.
- **Ground truth for narrative relevance is partially subjective.** We need a consistent human review process to label narrative validity during early operation.
