# Probability Framework

This document defines the mathematical model for combining dimension scores into probability estimates. It also defines what these probabilities mean, what they don't mean, and how to avoid misinterpreting them.

---

## Why Probabilities, Not Scores

A raw score like 0.75 on a 0–1 scale is ambiguous. Does it mean 75% chance of something? 75% of maximum quality? It's unclear.

The probability framework names what is being estimated:
- `P_potential`: estimated probability that a meaningful opportunity window exists or will exist
- `P_failure`: estimated probability of the token failing in a way that eliminates the opportunity (rug, exhaustion, fakeout)
- `net_potential`: combines both — the probability-adjusted opportunity strength
- `confidence_score`: quality of the evidence used to produce the estimates

These are not precise mathematical probabilities derived from statistical models with calibrated training sets. They are **structured, weighted estimates** that behave like probabilities. The difference matters.

---

## P_potential

**Definition:** Estimated probability that this token has a remaining meaningful opportunity window.

**Components:**

| Component | Weight | Notes |
|---|---|---|
| Narrative Relevance (NR) | 0.25 | Core signal — if narrative is weak, opportunity is weak |
| Authenticity / OG Score (OG) | 0.20 | High authenticity = less risk of narrative capture by copycats |
| Momentum Quality (MQ) | 0.20 | Organic momentum is more sustainable |
| Attention Strength (AS) | 0.20 | Strong external narrative extends the window |
| Timing Quality (TQ) | 0.15 | Earlier in lifecycle = more potential remaining |

**Formula:**
```
P_potential = (NR × 0.25) + (OG × 0.20) + (MQ × 0.20) + (AS × 0.20) + (TQ × 0.15)
```

**Range:** [0.0, 1.0]

**Interpretation:**
- 0.0–0.30: Weak or no identified opportunity signal
- 0.30–0.50: Marginal opportunity signal, high uncertainty
- 0.50–0.70: Moderate opportunity signal
- 0.70–0.85: Strong opportunity signal
- 0.85–1.0: Very strong opportunity signal (rare; requires near-perfect scores across dimensions)

---

## P_failure

**Definition:** Estimated probability that this token will fail in a way that eliminates the opportunity window.

Failure modes include:
- Rug pull (deployer exits liquidity)
- Smart contract exploit
- Fakeout pump (coordinated dump after artificial pump)
- Narrative exhaustion (the trend dies before price action matures)
- Liquidity removal (not necessarily a rug — market maker exits)
- Copycat capture (a competitor token captures the narrative, leaving this one behind)

**Components:**

| Component | Weight | Notes |
|---|---|---|
| Rug Risk Score (RR) | 0.35 | Structural/deployer risk — most direct failure signal |
| Fakeout / Coordination Risk (FR) | 0.25 | Derived from momentum analysis — is this engineered? |
| Narrative Exhaustion Risk (ER) | 0.20 | Inverse of timing quality — late-stage tokens face exhaustion |
| Copycat Capture Risk (CR) | 0.10 | If this is a copycat, probability narrative goes to OG instead |
| Liquidity Risk (LR) | 0.10 | Thin or locked liquidity creates execution risk |

**Fakeout Risk derivation:**
```
FR = 1 - MomentumQuality
```
(Low quality momentum = high fakeout risk)

**Narrative Exhaustion Risk derivation:**
```
ER = 1 - TimingQuality
```
(Late in lifecycle = high exhaustion risk)

**Copycat Capture Risk derivation:**
```
CR = 1 - OGScore
```
(If probably a copycat, risk of narrative going elsewhere is high)

**Liquidity Risk:**
Derived from on-chain liquidity data. Not a dimension score — computed directly from chain state.

**Formula:**
```
P_failure = (RR × 0.35) + (FR × 0.25) + (ER × 0.20) + (CR × 0.10) + (LR × 0.10)
```

**Range:** [0.0, 1.0]

**Interpretation:**
- 0.0–0.20: Low observed failure signals
- 0.20–0.40: Moderate failure risk — proceed with caution
- 0.40–0.65: High failure risk — significant red flags present
- 0.65–0.80: Very high failure risk — most tokens in this range fail
- 0.80–1.0: Critical failure risk — strong rug/scam indicators

---

## net_potential

**Definition:** The combined estimate of opportunity strength, discounted by failure probability.

**Formula:**
```
net_potential = P_potential × (1 - P_failure)
```

**Range:** [0.0, 1.0]

**Why this formula:** `net_potential` answers the question "given that this might fail, what's the adjusted opportunity strength?" It is not the probability of a specific return — it is a composite indicator.

**Worked example:**
```
P_potential = 0.78 (strong narrative, good timing, solid momentum)
P_failure   = 0.42 (medium-high rug risk, some concentration)

net_potential = 0.78 × (1 - 0.42)
              = 0.78 × 0.58
              = 0.45
```

An alert with `net_potential = 0.45` and `P_failure = 0.42` is not the same as `net_potential = 0.45` with `P_failure = 0.10`. Both inputs must be shown.

---

## confidence_score

**Definition:** Quality of the evidence used to compute the estimates. Not a measure of opportunity quality.

**A high confidence score means: we have good evidence for our estimate.**
**A low confidence score means: we are guessing with limited data.**

A high-confidence bad token is still a bad token. A low-confidence good token might be good or might be noise.

**Components:**

| Factor | Weight | Notes |
|---|---|---|
| Source count | 0.25 | More independent sources = higher confidence |
| Source diversity | 0.25 | Mix of source types > many sources of same type |
| Data completeness | 0.30 | Missing dimension data reduces confidence |
| Ambiguity level | 0.20 | High ambiguity in narrative matching or OG resolution reduces confidence |

**Formula:**
```
confidence_score = (source_count_score × 0.25) 
                 + (source_diversity_score × 0.25)
                 + (data_completeness_score × 0.30)
                 + (1 - ambiguity_score) × 0.20
```

**Range:** [0.0, 1.0]

**Data completeness calculation:**
```
completeness = (available_dimensions / required_dimensions)
```
Where required_dimensions = 6. Each missing dimension reduces completeness by 1/6 ≈ 0.167.

**Source count score (normalized):**
```
source_count_score = min(source_count / MAX_EXPECTED_SOURCES, 1.0)
```
Where `MAX_EXPECTED_SOURCES` is a configuration value (e.g., 5).

---

## Avoiding Fake Precision

These formulas produce numbers like `0.572` or `0.834`. These look precise. They are not.

The inputs (dimension scores) are themselves estimates with significant uncertainty. The formula propagates uncertainty in the inputs. The output should not be displayed with more precision than is meaningful.

**Display conventions:**
- Round all scores to two decimal places maximum
- Consider displaying ranges rather than point estimates (e.g., "0.55–0.65") when confidence is below 0.6
- Always display `confidence_score` alongside probability estimates
- Never display a probability estimate without contextual framing

**Example of acceptable display:**
```
net_potential: 0.57 (confidence: 0.74)
P_potential: 0.83 | P_failure: 0.31
```

**Example of unacceptable display:**
```
Probability of success: 57.3%  ← implies false precision, implies "success" is binary
```

---

## Weight Configuration

The weights above are starting defaults. They are **configurable parameters**, not hardcoded constants.

These weights should be revised over time as calibration data accumulates. A weight set that is well-calibrated against actual outcomes is better than the initial defaults.

**When to revise weights:**
- After 50+ alerted events with observable outcomes
- When calibration analysis shows systematic over/under-prediction in a dimension
- When new source types are added that change the reliability of specific dimensions

**How to revise:**
- Document the old weights and why they were changed
- Revise the formula in this document before changing code
- Re-run historical scoring against the new weights before deploying

---

## Open Questions

- **Are these weights correct?** Unknown. They represent a reasonable starting prior. Calibration is required.
- **Should P_failure use a different combination function?** The additive weighted model is simple and interpretable. A multiplicative model might better represent "any one of these kills the token" semantics. This is an open design question.
- **How should we handle extreme values?** If a single dimension is at 1.0 (e.g., perfect rug signal), should it override the weighted average? Currently it does not — a perfect rug risk score of 1.0 contributes 0.35 to P_failure, not the full 1.0. This may need revision.
- **Confidence score floor:** Should there be a minimum confidence threshold below which no alert is generated? Currently there is not. This may be desirable to prevent low-quality alerts from flooding outputs.
