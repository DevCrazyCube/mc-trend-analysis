# End-to-End Verification Guide — Narrative Intelligence & Competition

This document describes how to manually verify the strict selection engine is working correctly. Use this after deploying changes to the narrative intelligence, competition, or alert gating layers.

**Goal:** Confirm that the system enforces winner-takes-all, suppresses losers with reasons, and stays silent when no signal is strong enough.

---

## 1. Verify Zero-Alert Cycles (Silence Is Expected)

The system must emit zero alerts when no narrative reaches RISING+ state.

### Via API

```bash
# Check last cycle stats
curl -H "Authorization: Bearer $API_KEY" http://localhost:8765/api/health | jq '.last_cycle'

# Expected when no strong signals exist:
# "alerts_created": 0, "suppressed": >= 0, "errors": []
```

### Via Competition Endpoint

```bash
curl -H "Authorization: Bearer $API_KEY" http://localhost:8765/api/competition | jq '.'

# Check: narrative_outcomes should show competition_status values.
# If all are "below_threshold" or have state WEAK/EMERGING, zero alerts is correct.
# summary.narrative_winners == 0 confirms no narrative won.
```

### Via Silence Indicator

```bash
curl -H "Authorization: Bearer $API_KEY" http://localhost:8765/api/health/silence | jq '.'

# Returns structured explanation of why no output was produced.
# Check: silence_reasons array should contain specific codes like
# "no_narrative_reached_alert_eligibility" or "all_candidates_suppressed".
```

### Via Database (Direct)

```sql
-- Count narratives by state
SELECT state, COUNT(*) FROM narratives GROUP BY state;

-- If no RISING or TRENDING rows exist, zero alerts is correct behavior.
```

---

## 2. Verify Single-Winner Behavior

Only one token per narrative should reach alert classification.

### Via Competition Endpoint

```bash
curl -H "Authorization: Bearer $API_KEY" http://localhost:8765/api/competition | jq '.token_outcomes'

# For each narrative_id group:
# - Exactly ONE entry should have token_competition_status == "winner"
# - All others should have token_competition_status == "suppressed"
# - Every suppressed token must have non-empty suppression_reasons
```

### Via Rejected Candidates

```bash
curl -H "Authorization: Bearer $API_KEY" http://localhost:8765/api/candidates | jq '.candidates[] | {token_name, rejection_reasons}'

# Suppressed tokens appear here with structured rejection_reasons.
# Look for codes: "lost_to_stronger_token", "winner_margin_not_met"
```

### Via Database (Direct)

```sql
-- Check narrative competition status
SELECT narrative_id, description, state, narrative_strength,
       competition_status, competition_rank
FROM narratives
WHERE state IN ('EMERGING', 'RISING', 'TRENDING')
ORDER BY cluster_id, competition_rank;

-- Per cluster_id group: only rank 1 should have competition_status = 'winner' or 'no_contest'
```

---

## 3. Verify Suppression Reasons

Every non-winner must carry machine-readable suppression reasons.

### Suppression Reason Codes Reference

| Code | Meaning |
|------|---------|
| `lost_to_stronger_narrative` | Another narrative in same cluster had higher strength |
| `lost_to_stronger_token` | Another token in same narrative had higher net_potential |
| `below_min_strength` | Narrative strength below winner_min_strength (default 0.30) |
| `below_min_velocity` | Narrative velocity is stalled |
| `insufficient_source_count` | Fewer than min_sources sources |
| `insufficient_source_diversity` | Too few source types |
| `not_top_in_cluster` | Not rank 1 in cluster competition |
| `winner_margin_not_met` | Close to winner but strict winner-takes-all enforced |
| `narrative_state_too_low` | State below RISING (WEAK, EMERGING, FADING) |
| `narrative_dead` | Narrative in terminal DEAD state |
| `narrative_fading` | Narrative declining |

### Verification

```bash
# Competition endpoint — all non-winners must have reasons
curl -H "Authorization: Bearer $API_KEY" http://localhost:8765/api/competition | \
  jq '.narrative_outcomes[] | select(.competition_status != "winner" and .competition_status != "no_contest") | {narrative_id, competition_status, suppression_reasons}'

# Every result MUST have a non-empty suppression_reasons array.
# Each reason MUST have: code, actual, threshold, detail
```

---

## 4. Verify Winner Explanations

Every winner must carry a full justification breakdown.

```bash
# Narrative winners
curl -H "Authorization: Bearer $API_KEY" http://localhost:8765/api/competition | \
  jq '.narrative_outcomes[] | select(.competition_status == "winner" or .competition_status == "no_contest") | {narrative_id, winner_explanation}'

# Each winner_explanation must include:
# - strength_breakdown: source_count_score, velocity_score, recency_score, diversity_score
# - velocity: current velocity + state
# - source_metrics: count + types
# - cluster_context: cluster_size + rank
# - runner_up (if applicable): strength difference
```

```bash
# Token winners
curl -H "Authorization: Bearer $API_KEY" http://localhost:8765/api/competition | \
  jq '.token_outcomes[] | select(.token_competition_status == "winner") | {token_id, winner_explanation}'

# Each winner_explanation must include:
# - net_potential, rank, total_competitors, margin_over_second
```

---

## 5. Verify Clustering Correctness

Narratives about the same topic should cluster together. Unrelated narratives should remain separate.

```sql
-- Show clusters with their members
SELECT cluster_id, narrative_id, description, anchor_terms, narrative_strength
FROM narratives
WHERE cluster_id IS NOT NULL AND state NOT IN ('DEAD', 'MERGED')
ORDER BY cluster_id, narrative_strength DESC;

-- Check for false merges: are there unrelated topics sharing a cluster_id?
-- Check for false splits: are there similar topics with different cluster_ids?
```

### What to Look For

**False merge indicators:**
- Two narratives in the same cluster with completely unrelated descriptions
- Cluster triggered by a single overly-generic term (e.g., "AI", "MOON")

**False split indicators:**
- Two narratives about the same event/topic with different cluster_ids
- Near-identical anchor terms but different cluster_ids

---

## 6. Verify Alert Gating (RISING+ Only)

Alerts must only fire for RISING or TRENDING narratives. EMERGING narratives must be blocked.

```bash
# Check active alerts and their narrative states
curl -H "Authorization: Bearer $API_KEY" http://localhost:8765/api/alerts | \
  jq '.alerts[] | {alert_id, narrative_name, alert_type}'

# Cross-reference with narrative states:
curl -H "Authorization: Bearer $API_KEY" http://localhost:8765/api/narratives | \
  jq '.narratives[] | {narrative_id, state, narrative_strength}'

# Every alerted narrative MUST be in RISING or TRENDING state.
# If any alert references an EMERGING narrative, the gating is broken.
```

---

## 7. Quick Smoke Test (Demo Data)

Run the system once with demo data and verify all invariants:

```bash
python -m mctrend --once
```

Then check:
1. `GET /api/competition` — returns narrative and token outcomes
2. `GET /api/health/silence` — if zero alerts, explains why
3. `GET /api/candidates` — shows suppressed tokens with reasons
4. `GET /api/health` — last_cycle shows no errors

---

## 8. Automated Test Coverage

The following test suites cover the intelligence engine:

| Test Class | File | Count | Coverage |
|------------|------|-------|----------|
| TestVelocity | tests/unit/test_narrative_intelligence.py | 6 | Velocity computation |
| TestStrength | tests/unit/test_narrative_intelligence.py | 6 | Strength formula |
| TestLifecycle | tests/unit/test_narrative_intelligence.py | 11 | State machine |
| TestQualityGating | tests/unit/test_narrative_intelligence.py | 8 | Scoring eligibility |
| TestAlertEligibility | tests/unit/test_narrative_intelligence.py | 6 | Alert gating (RISING+ only) |
| TestSuppressionReasons | tests/unit/test_narrative_intelligence.py | 7 | Reason codes |
| TestNarrativeCompetition | tests/unit/test_narrative_intelligence.py | 6 | Winner selection |
| TestTokenCompetition | tests/unit/test_narrative_intelligence.py | 7 | Token winner-takes-all |
| TestClustering | tests/unit/test_narrative_intelligence.py | 8 | Union-find clustering |
| TestPipelineIntegration | tests/integration/test_pipeline.py | 5 | End-to-end cycle |

Run all: `python -m pytest tests/ -x -q`
