# Narrative Intelligence System

This document defines the narrative quality evaluation, lifecycle management, competition, and winner selection system. It supersedes the flat attention_score mechanism and the static EMERGING state default.

**This is the source of truth for narrative intelligence behavior.** If code disagrees with this document, this document is right.

Reference: `docs/intelligence/narrative-linking.md` (matching), `docs/intelligence/scoring-model.md` (dimensions)

---

## Design Principles

1. **Not all narratives are equal.** The system must separate noise from real trends.
2. **Reinforcement is signal.** Multiple independent sources confirming the same topic is the strongest indicator.
3. **Velocity is signal.** Growing attention matters more than static attention.
4. **Stagnation is anti-signal.** A narrative with no new sources and declining velocity is dying.
5. **Only winners matter.** At any moment, only the strongest narrative per competitive group should drive alerts.
6. **No signal = no alert.** If no narrative is strong enough, the system emits nothing.

---

## 1. Narrative Velocity

Velocity measures how fast a narrative is gaining attention. It is the **most important missing signal** in the current system.

### Computation

```
velocity = source_events_in_window / window_size_minutes
```

Where:
- `source_events_in_window`: count of distinct source updates (new sources OR existing source re-confirmations) within the velocity window
- `window_size_minutes`: configurable, default 30 minutes

### Velocity Delta

```
velocity_delta = current_velocity - previous_velocity
```

Where `previous_velocity` is the velocity computed at the previous pipeline cycle.

### Classification

| Velocity State | Condition |
|---|---|
| `accelerating` | velocity_delta > 0 AND velocity > 0 |
| `stable` | velocity_delta ~= 0 (within +/- 0.01) AND velocity > 0 |
| `decelerating` | velocity_delta < 0 AND velocity > 0 |
| `stalled` | velocity == 0 (no events in window) |

### Storage

On the narrative record:
- `narrative_velocity`: float (events per minute in window)
- `velocity_delta`: float (change from previous cycle)
- `velocity_state`: enum string (`accelerating`, `stable`, `decelerating`, `stalled`)
- `velocity_updated_at`: ISO timestamp of last velocity computation

---

## 2. Narrative Strength

Replaces the flat `attention_score`. A computed metric that dynamically reflects narrative quality.

### Formula

```
strength = (
    source_count_score * 0.30
  + velocity_score     * 0.35
  + recency_score      * 0.25
  + diversity_score    * 0.10
)
```

### Sub-scores

| Sub-score | Computation |
|---|---|
| `source_count_score` | `clip(source_count / max_source_count, 0, 1)`, where `max_source_count` defaults to 5 |
| `velocity_score` | `clip(velocity / max_velocity, 0, 1)`, where `max_velocity` defaults to 0.5 events/min |
| `recency_score` | `clip(1.0 - minutes_since_last_update / decay_minutes, 0, 1)`, where `decay_minutes` defaults to 120 |
| `diversity_score` | `clip(distinct_source_type_count / max_source_types, 0, 1)`, where `max_source_types` defaults to 4 |

### Storage

- `narrative_strength`: float [0, 1] stored on the narrative record
- Replaces `attention_score` as the primary quality metric
- `attention_score` retained for backward compatibility but not used in scoring decisions

---

## 3. Narrative Lifecycle State Machine

### States

```
WEAK → EMERGING → RISING → TRENDING → FADING → DEAD
```

| State | Entry Conditions |
|---|---|
| `WEAK` | source_count < min_sources OR strength < weak_threshold |
| `EMERGING` | source_count >= min_sources AND strength >= emerging_threshold |
| `RISING` | velocity_state == accelerating AND source_count >= min_sources AND strength >= rising_threshold |
| `TRENDING` | velocity_state in (accelerating, stable) AND source_count >= trending_min_sources AND strength >= trending_threshold |
| `FADING` | velocity_state == decelerating OR (strength dropping AND below fading_threshold) |
| `DEAD` | no source updates for dead_timeout_minutes OR strength < dead_threshold |

### Default Thresholds

| Parameter | Default | Env Var |
|---|---|---|
| `min_sources` | 2 | `NARRATIVE_MIN_SOURCES` |
| `weak_threshold` | 0.15 | `NARRATIVE_WEAK_THRESHOLD` |
| `emerging_threshold` | 0.20 | `NARRATIVE_EMERGING_THRESHOLD` |
| `rising_threshold` | 0.35 | `NARRATIVE_RISING_THRESHOLD` |
| `trending_threshold` | 0.55 | `NARRATIVE_TRENDING_THRESHOLD` |
| `trending_min_sources` | 3 | `NARRATIVE_TRENDING_MIN_SOURCES` |
| `fading_threshold` | 0.25 | `NARRATIVE_FADING_THRESHOLD` |
| `dead_threshold` | 0.10 | `NARRATIVE_DEAD_THRESHOLD` |
| `dead_timeout_minutes` | 120 | `NARRATIVE_DEAD_TIMEOUT_MINUTES` |
| `velocity_window_minutes` | 30 | `NARRATIVE_VELOCITY_WINDOW_MINUTES` |
| `max_velocity` | 0.5 | `NARRATIVE_MAX_VELOCITY` |
| `recency_decay_minutes` | 120 | `NARRATIVE_RECENCY_DECAY_MINUTES` |

### Transition Rules

1. State is re-evaluated every pipeline cycle.
2. Transitions are always logged with: previous_state, new_state, timestamp, reason.
3. Upward transitions (WEAK→EMERGING→RISING→TRENDING) require meeting ALL entry conditions.
4. Downward transitions (TRENDING→FADING→DEAD) are triggered by ANY failing condition.
5. A DEAD narrative cannot transition back up. If the topic resurges, a new narrative is created.
6. WEAK narratives are created but excluded from token scoring.

---

## 4. Narrative Quality Gating

Narratives must meet minimum quality thresholds before they can influence token scoring.

### Minimum Requirements for Scoring Eligibility

| Requirement | Threshold |
|---|---|
| Narrative state | >= EMERGING (WEAK excluded) |
| Source count | >= `min_sources` (default 2) |
| Strength | >= `emerging_threshold` (default 0.20) |

### Behavior

- Tokens linked to WEAK narratives: link is created but NOT scored. Token stays in `linked` status.
- When a WEAK narrative transitions to EMERGING or higher, its linked tokens become eligible for scoring in the next cycle.
- When a narrative transitions to DEAD, its linked tokens are flagged for re-evaluation.

---

## 5. Narrative Clustering (De-duplication)

### Problem

Multiple narratives about the same topic may exist with different anchor terms or phrasings. This fragments signal strength.

### Approach

Deterministic clustering using anchor term overlap and shared token links:

1. **Term Overlap**: Two narratives share >= 50% of their anchor terms (case-insensitive).
2. **Token Overlap**: Two narratives have >= 2 tokens linked to both.
3. **Explicit Merge**: During `merge_narratives`, if an incoming event matches an existing narrative by anchor terms, merge rather than create.

### Cluster Behavior

When narratives are clustered:
- Sources are unioned across the cluster
- Velocity is computed across all sources in the cluster
- Strength is computed from the combined signal
- The cluster is represented by the narrative with the highest strength (the **cluster leader**)
- Non-leader narratives in a cluster are marked `state = MERGED` with a `merged_into` reference

### Storage

- `cluster_id`: nullable string on the narrative record. Narratives in the same cluster share this ID.
- `merged_into`: nullable narrative_id pointing to the cluster leader.

---

## 6. Competition Layer

### Narrative Competition

Within each pipeline cycle, narratives compete for dominance:

1. Group narratives by cluster (or treat unclustered narratives as solo groups).
2. Within each group, the narrative with the highest `narrative_strength` is the **winner**.
3. The winner must have `strength >= winner_min_strength` (default 0.30, configurable).
4. If no narrative in the group exceeds the minimum strength, there is **no winner** and no tokens in that group produce alerts.
5. Non-winner narratives in a group are marked `competition_status = OUTCOMPETED`.

### Token Competition

Within the winner narrative's linked tokens:

1. Rank tokens by their computed `net_potential` score.
2. The top token is the **winner token**.
3. Other tokens are suppressed unless they exceed the winner by `token_competition_margin` (default 0.05).
4. Suppressed tokens are still scored and stored but do not generate alerts.

### Configuration

| Parameter | Default | Env Var |
|---|---|---|
| `winner_min_strength` | 0.30 | `NARRATIVE_WINNER_MIN_STRENGTH` |
| `token_competition_margin` | 0.05 | `TOKEN_COMPETITION_MARGIN` |

---

## 7. Alert Gating (Final Layer)

Alerts fire only when ALL of the following are true:

1. Token is linked to a narrative with state >= RISING (or EMERGING if no RISING+ narratives exist in this cycle).
2. The narrative is the winner of its competitive group (or has no competition).
3. The token is the winner token within its narrative (or is within margin of the winner).
4. Standard alert threshold checks pass (net_potential, p_failure, confidence).

If condition 1 or 2 fails: no alert, reason logged as `narrative_quality_gate_failed`.
If condition 3 fails: no alert, reason logged as `token_outcompeted`.

---

## 8. Time Decay

All narrative metrics decay over time:

- **Strength decays** if no new source events arrive. The `recency_score` component naturally handles this.
- **Velocity decays** to 0 if no events occur within the velocity window.
- **State transitions downward** when decay causes thresholds to be crossed.
- **A narrative with no updates for `dead_timeout_minutes` transitions to DEAD** regardless of other metrics.

This is not a separate mechanism — it is a natural consequence of the velocity and strength computations being time-aware.

---

## 9. Operator Visibility

### Required Dashboard Panels

1. **Active Narratives**: state, strength, velocity, velocity_state, source_count, competition_status, winner flag
2. **Rejected Narratives**: narratives in WEAK state with reason for rejection (low sources, no velocity, etc.)
3. **Competition Results**: per cycle, which narrative won each group and why others lost
4. **Narrative Timeline**: per narrative, source additions over time, strength/velocity curves, state transitions

### Logging

Every state transition, every competition result, and every quality gate rejection must be logged with structlog at INFO level with structured fields.

---

## Implementation Sequence

1. Add `NarrativeIntelligence` module: velocity computation, strength computation, state machine, quality gating
2. Add narrative config to `Settings`
3. Wire into pipeline between Step 3 (normalize events) and Step 4 (correlate)
4. Add competition layer after Step 5 (scoring), before Step 6 (alert classification)
5. Add API endpoints and dashboard panels
6. Add tests for velocity, strength, state machine, quality gating, competition

---

## What This System Is Not

- Not an LLM-powered topic detector (deterministic only)
- Not a social media sentiment analyzer
- Not a prediction of narrative longevity
- Not a guarantee that the winning narrative/token is profitable

This is a **signal quality filter**. It separates strong, reinforced, accelerating signals from noise. The scoring model and alert classifier downstream decide what to do with the survivors.
