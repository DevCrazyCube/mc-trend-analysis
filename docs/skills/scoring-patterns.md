# Scoring Patterns

This document defines reusable patterns for computing dimension scores reliably and correctly.

---

## Pattern 1: Dimension Score Functions Are Pure

Every dimension score function must be a pure function:
- Takes inputs, returns a score
- Has no side effects
- Does not fetch data
- Does not access external state

**Why:** Pure functions are testable, predictable, and auditable. A scoring function that fetches its own data is untestable in isolation and creates coupling between scoring logic and data access.

**Implementation pattern:**
```python
def score_rug_risk(
    deployer_risk: float | None,
    concentration_risk: float | None,
    clustering_risk: float | None,
    liquidity_risk: float | None,
    contract_risk: float | None,
) -> tuple[float, list[str]]:
    """
    Returns (rug_risk_score, risk_flags_list).
    All inputs may be None (data gaps); handle with conservative defaults.
    """
    ...
```

---

## Pattern 2: Conservative Defaults for Missing Inputs

When a scoring function receives `None` for an input, it applies the conservative default defined in `docs/intelligence/probability-framework.md`. The default is applied inside the scoring function — not by the caller.

```python
def score_rug_risk(deployer_risk, concentration_risk, ...):
    deployer = deployer_risk if deployer_risk is not None else DEPLOYER_DEFAULT  # 0.50
    concentration = concentration_risk if concentration_risk is not None else CONCENTRATION_DEFAULT  # 0.55
    ...
```

Defaults are defined as named constants, not magic numbers. Constants reference the document that defines their values.

---

## Pattern 3: Score + Explanation Co-production

Every scoring function produces a score AND an explanation of what drove that score. The explanation is a list of signal strings.

```python
def score_momentum_quality(...) -> tuple[float, list[str]]:
    signals = []
    
    if volume_concentration < 0.30:
        signals.append("volume_distributed_across_many_wallets")
    elif volume_concentration > 0.70:
        signals.append("SUSPICIOUS_VOLUME_CONCENTRATION")
    
    ...
    
    return final_score, signals
```

The signals list feeds into the `reasoning` field of the alert and the `dimension_details` field of the ScoredToken record. Without it, the score cannot be explained.

---

## Pattern 4: Bounded Score Outputs

All scoring functions must return values in [0.0, 1.0]. Use `clip()` or `clamp()` to enforce this:

```python
score = clip(raw_score, 0.0, 1.0)
```

Never return values outside this range. A bug in the scoring arithmetic that produces 1.3 or -0.2 should be caught at the function boundary, not silently propagate to downstream computations.

---

## Pattern 5: Weighted Combination Pattern

The standard pattern for combining sub-scores with weights:

```python
def combine_with_weights(
    components: list[tuple[float, float]]  # [(value, weight), ...]
) -> float:
    """Weighted average. All weights should sum to 1.0."""
    assert abs(sum(w for _, w in components) - 1.0) < 0.001, "Weights must sum to 1.0"
    return sum(v * w for v, w in components)
```

The assertion ensures weight configuration errors are caught at runtime, not silently produce wrong results.

---

## Pattern 6: Dimension Score Isolation

Each dimension score is computed independently. No dimension's computation should depend on another dimension's output.

Violations of this pattern create hidden dependencies that make the model harder to reason about and harder to tune. If you find yourself passing the narrative score into the rug risk function, stop and redesign.

**The only place where dimension scores are combined is in the Scoring Aggregator** (`docs/architecture/components.md`), which computes P_potential and P_failure from the full set of dimension outputs.

---

## Pattern 7: Scoring Metadata

Every scoring run produces a `ScoredToken` record with a full audit trail. The scoring function must return enough information to populate the `dimension_details` field:

```python
ScoredToken.dimension_details = {
    "narrative_relevance": {
        "score": 0.91,
        "signals": ["exact_anchor_match", "multi_source_narrative", "narrative_age_fresh"],
        "inputs": { "match_confidence": 0.97, "source_type_count": 3, "narrative_age_hours": 0.3 }
    },
    "rug_risk": {
        "score": 0.38,
        "signals": ["HIGH_HOLDER_CONCENTRATION", "new_deployer"],
        "inputs": { "top5_pct": 0.62, "deployer_age_hours": 12, "liquidity_locked": False }
    },
    ...
}
```

This level of detail is required for debugging scoring anomalies and for calibration analysis.

---

## Pattern 8: Freshness-Weighted Scoring

When data is stale but not missing, apply a freshness discount:

```python
def apply_freshness_discount(score: float, data_age_minutes: int, threshold_minutes: int) -> float:
    if data_age_minutes <= threshold_minutes:
        return score  # fresh data, no discount
    
    staleness_ratio = (data_age_minutes - threshold_minutes) / threshold_minutes
    discount = clip(staleness_ratio * MAX_STALENESS_DISCOUNT, 0, MAX_STALENESS_DISCOUNT)
    return score * (1 - discount)
```

`MAX_STALENESS_DISCOUNT` is configurable (default: 0.30 — stale data can reduce a score by at most 30%).

---

## Pattern 9: Handling Contradictory Signals

Sometimes signals within a dimension contradict each other (e.g., holder count looks organic but volume concentration is suspicious). The scoring function should:

1. Score each sub-signal independently
2. Combine with weights as normal
3. When contradiction exists, add a `MIXED_SIGNALS` flag to the signals list
4. Do not attempt to "resolve" the contradiction by choosing one signal — represent both

Contradictory signals often indicate an ambiguous situation where confidence should be lower. The `MIXED_SIGNALS` flag contributes to reduced confidence in the overall score.

---

## Pattern 10: Testing Scoring Functions

Every scoring function must have tests covering:

1. **Happy path:** Normal inputs produce expected score range
2. **All-null inputs:** Conservative defaults produce conservative (not zero) scores
3. **Boundary values:** Inputs at exact threshold values produce the expected classification
4. **Known patterns:** Inputs matching known rug or organic patterns produce expected tier
5. **Weight consistency:** The sum of weights is asserted in every test run

Tests use fixed, documented inputs with calculated expected outputs. Do not use random inputs — scores must be deterministic and testable.
