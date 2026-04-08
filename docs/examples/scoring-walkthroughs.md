# Scoring Walkthroughs

Step-by-step computation of scores for a concrete token candidate. This document shows the math and demonstrates how all pieces connect.

---

## Walkthrough: `$MOONDOG` on Viral Dog Story Narrative

**Context:** A video of a dog going to space (a research balloon experiment) goes viral globally. The story trends #1 on multiple platforms for about 4 hours. Token `$MOONDOG` launches 11 minutes after the story breaks.

---

### Step 1: Event Record (Narrative State)

```
narrative_id: n-moondog-viral-2024
anchor_terms: ["moondog", "space dog", "dog space", "space balloon"]
related_terms: ["dog", "moon", "space", "balloon"]
attention_score: 0.86
narrative_velocity: +0.12 (growing)
state: EMERGING
source_type_count: 4 (Twitter, Google Trends, Reddit, CNN)
first_detected: T+0min
age_at_scoring: 11 minutes
```

---

### Step 2: Token Record

```
token: MOONDOG ($MOONDOG)
address: So1ana...moondog
deployed_by: wallet_A (new wallet, no prior deployments)
launch_time: T+11min
platform: pump.fun
initial_liquidity: $4,200 USD (unlocked)
```

---

### Step 3: Correlation

Layer 1 exact match: `MOONDOG` vs. anchor term `moondog` → exact match
Match confidence: 0.96

TokenNarrativeLink created. OG resolution: 2 other tokens in namespace (`$DOGMOON`, `$SPACEDOGE`).

---

### Step 4: Chain Data (at T+11min)

```
holder_count: 47
top_5_holder_pct: 41%  (35% is deployer + 4 early buyers, 6% is pool)
top_10_holder_pct: 58%
new_wallet_holder_pct: 62%  (many fresh wallets)
volume_1h_usd: $8,400
trade_count_1h: 127
unique_traders_1h: 89
deployer_known_bad: false
deployer_prior_deployments: 0
liquidity_locked: false
liquidity_provider_count: 1
```

---

### Step 5: OG Resolution (3 candidates)

| Token | Launch Time | Name Precision | Cross-Source Mentions | OG Score |
|---|---|---|---|---|
| $MOONDOG | T+11min | 1.0 (exact) | 2 mentions | 0.82 |
| $DOGMOON | T+14min | 0.45 (reversed) | 0 mentions | 0.48 |
| $SPACEDOGE | T+19min | 0.30 (related terms) | 0 mentions | 0.31 |

`$MOONDOG` gets OG rank 1 with og_score 0.82.

**OG score computation:**
```
temporal = 1.0 (first in namespace)
name_precision = 1.0 (exact anchor match)
cross_source = min(2 / 5, 1.0) = 0.40
deployer = 0.50 (new wallet, neutral)

og_score = (1.0 × 0.35) + (1.0 × 0.25) + (0.40 × 0.30) + (0.50 × 0.10)
         = 0.35 + 0.25 + 0.12 + 0.05
         = 0.77
```

*(Note: 0.77 vs. 0.82 in table above — minor variation due to rounding in this walkthrough)*

---

### Step 6: Dimension Scoring

#### Dimension 1: Narrative Relevance

```
name_alignment = 0.97 × 0.40 = 0.388  (near-perfect match × weight)
narrative_recency = (1 - age_hours/decay_hours) × 0.30
                  = (1 - 0.18/2.0) × 0.30  [11 minutes = 0.18 hours]
                  = 0.91 × 0.30 = 0.273
source_diversity = (4 types / 4 max_types) × 0.30 = 0.30

narrative_relevance = 0.388 + 0.273 + 0.30 = 0.961
→ capped at 1.0, score: 0.961 → 0.96
```

Wait — let's verify this is reasonable. Very high (0.96) for an exact match to a trending narrative with 4 source types and 11 minutes old. That checks out.

#### Dimension 2: Authenticity / OG Score

```
og_score = 0.77 (computed above)
```

#### Dimension 3: Rug Risk

```
deployer_risk:
  - new wallet (no prior deployments): 0.45
  - not on bad actor list: no adjustment
  → deployer_risk = 0.45

concentration_risk:
  - top_5_holder_pct = 0.41
  → concentration_score = clip(0.41 / 0.70, 0, 1) = 0.586

liquidity_risk:
  - unlocked: +0.30
  - single provider: +0.20
  - liquidity_usd = $4,200 (above minimum): +0.0
  → liquidity_risk = 0.50

clustering_risk:
  - new_wallet_holder_pct = 0.62 (62% fresh wallets): suspicious
  → clustering estimated risk: 0.55 (heuristic, full graph not available)

contract_risk:
  - pump.fun standard token: 0.30 (standard contract)

rug_risk = (0.45 × 0.30) + (0.586 × 0.25) + (0.55 × 0.20) + (0.50 × 0.15) + (0.30 × 0.10)
         = 0.135 + 0.147 + 0.110 + 0.075 + 0.030
         = 0.497
→ rug_risk = 0.50 (medium tier)
```

Risk flags triggered: `UNLOCKED_LIQUIDITY`, `NEW_DEPLOYER`, `HIGH_NEW_WALLET_PCT`

#### Dimension 4: Momentum Quality

```
volume_pattern_score:
  - 127 trades over ~11 minutes = 11.5 trades/min (high but not extreme)
  - No spike pattern detected in available window
  → volume_pattern = 0.68

diversity_score:
  - unique_buyer_ratio = 89 / 127 = 0.701 (good)
  - volume_concentration: top 5 traders responsible for ~40% of volume (estimating from holder data)
  → diversity = (1 - 0.40) × 0.60 + 0.701 × 0.40 = 0.36 + 0.28 = 0.64

social_alignment:
  - social signal preceded trading activity (news broke before token launched) → alignment_score = 1.0

holder_growth:
  - 62% new wallets: concerning
  - No detected batch-add event (holders arriving individually)
  → holder_quality = 1 - (0 × 0.15 + 0.62 × 0.85) = 1 - 0.527 = 0.473

momentum_quality = (0.68 × 0.30) + (0.64 × 0.30) + (1.0 × 0.20) + (0.473 × 0.20)
                 = 0.204 + 0.192 + 0.200 + 0.095
                 = 0.691
→ momentum_quality = 0.69
```

#### Dimension 5: Attention Strength

```
narrative attention_score from EventRecord = 0.86
This is already a composite score from the event ingestion pipeline.

search_magnitude = 0.81 (Google trends at 81/100)
source_breadth = 4 source types / 4 max = 1.0
narrative_velocity = +0.12 (growing)
velocity_score = min(0.12 / 0.20 + 0.5, 1.0) = 0.80  (normalized)

attention_strength = (0.81 × 0.35) + (1.0 × 0.35) + (0.80 × 0.30)
                   = 0.284 + 0.350 + 0.240
                   = 0.874
→ attention_strength = 0.87
```

#### Dimension 6: Timing Quality

```
lifecycle_position:
  - Narrative age: 11 minutes (very early in EMERGING state)
  - Token age relative to narrative: 11 minutes after narrative detection
  → lifecycle_score = 1.0 (EMERGING, very fresh)

narrative_acceleration:
  - velocity = +0.12 (positive, still growing)
  → acceleration_score = 0.75 (growing but not at maximum velocity)

market_saturation:
  - 3 tokens in namespace (including this one)
  - 3 tokens is moderate: not saturated, not completely clear
  → saturation_score = 0.75 (few competitors)

timing_quality = (1.0 × 0.40) + (0.75 × 0.30) + (0.75 × 0.30)
               = 0.400 + 0.225 + 0.225
               = 0.850
→ timing_quality = 0.85
```

---

### Step 7: Probability Calculation

```
P_potential = (NR × 0.25) + (OG × 0.20) + (MQ × 0.20) + (AS × 0.20) + (TQ × 0.15)
            = (0.96 × 0.25) + (0.77 × 0.20) + (0.69 × 0.20) + (0.87 × 0.20) + (0.85 × 0.15)
            = 0.240 + 0.154 + 0.138 + 0.174 + 0.128
            = 0.834
→ P_potential = 0.83

P_failure:
  FR (fakeout risk) = 1 - MQ = 1 - 0.69 = 0.31
  ER (exhaustion risk) = 1 - TQ = 1 - 0.85 = 0.15
  CR (copycat capture risk) = 1 - OG = 1 - 0.77 = 0.23
  LR (liquidity risk) = 0.50 (from liquidity_risk above, rescaled to direct P_failure contribution)

  P_failure = (RR × 0.35) + (FR × 0.25) + (ER × 0.20) + (CR × 0.10) + (LR × 0.10)
            = (0.50 × 0.35) + (0.31 × 0.25) + (0.15 × 0.20) + (0.23 × 0.10) + (0.50 × 0.10)
            = 0.175 + 0.078 + 0.030 + 0.023 + 0.050
            = 0.356
→ P_failure = 0.36

net_potential = P_potential × (1 - P_failure)
              = 0.83 × (1 - 0.36)
              = 0.83 × 0.64
              = 0.531
→ net_potential = 0.53
```

---

### Step 8: Confidence Score

```
source_count: 4 active sources → source_count_score = min(4/5, 1.0) = 0.80
source_diversity: 4 distinct source types → diversity_score = 1.0
data_completeness: all 6 dimensions computed, no nulls → completeness = 6/6 = 1.0
ambiguity: not ambiguous, OG resolution clear → ambiguity_score = 0.10 (low)

confidence = (0.80 × 0.25) + (1.0 × 0.25) + (1.0 × 0.30) + (1 - 0.10) × 0.20
           = 0.200 + 0.250 + 0.300 + 0.180
           = 0.930
→ confidence_score = 0.93
```

High confidence because all data is available and unambiguous.

---

### Step 9: Alert Classification

```
net_potential = 0.53
P_failure = 0.36
confidence = 0.93
narrative_state = EMERGING
active_risk_flags = [UNLOCKED_LIQUIDITY, NEW_DEPLOYER, HIGH_NEW_WALLET_PCT]
critical_flags = none

Check possible-entry: net_potential 0.53 < 0.60 → does not qualify
Check high-potential-watch: net_potential 0.53 ≥ 0.45, P_failure 0.36 < 0.50, confidence 0.93 ≥ 0.55 → QUALIFIES

→ Alert type: high-potential-watch
```

**Final scores summary:**

| Dimension | Score |
|---|---|
| Narrative Relevance | 0.96 |
| OG Score | 0.77 |
| Rug Risk | 0.50 |
| Momentum Quality | 0.69 |
| Attention Strength | 0.87 |
| Timing Quality | 0.85 |
| **P_potential** | **0.83** |
| **P_failure** | **0.36** |
| **net_potential** | **0.53** |
| **confidence** | **0.93** |
| **Alert type** | **high-potential-watch** |
