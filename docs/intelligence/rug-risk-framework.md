# Rug Risk Framework

This document defines how structural and behavioral risk signals are evaluated for each token.

**Critical disclaimer:** This framework produces risk estimates, not safety guarantees. A token with a low rug risk score can still be rugged. A token with a high rug risk score may not rug. This is a probability estimate based on observable signals, not a prediction of future behavior.

---

## What "Rug" Means in This Context

For this system, "rug risk" encompasses the broad category of failure modes where:
- Deployers deliberately exit with liquidity ("rug pull" in the strict sense)
- Liquidity is removed for any reason, making the token effectively untradeable
- A token was designed from the start as a fraud
- The deployer has the technical ability to drain, freeze, or destroy token value at will

This also includes adjacent risks:
- Coordinated insider dump (insiders hold majority and dump on retail)
- Freeze authority abuse (deployer can freeze accounts)
- Mint authority abuse (deployer can mint new supply, diluting holders)

---

## Risk Categories

### Category 1: Deployer Risk (Weight: 0.30)

**What it evaluates:** The history and behavior of the wallet that deployed the token.

**Signals:**

| Signal | Risk Contribution | Notes |
|---|---|---|
| Brand new wallet (< 10 prior transactions) | Medium | Could be privacy, could be serial deployer |
| Wallet with history of known rug deployments | Critical | Strongest single signal |
| Wallet with pattern of multiple simultaneous token deployments | High | Common in factory-rug operations |
| Wallet funded from known mixer | High | Privacy screen is concerning in this context |
| Wallet has legitimate history (multiple tokens, no exits) | Reduces risk | Not zero risk, but positive prior |
| Wallet funded from known exchange | Neutral | No signal either way |

**Scoring:**
- Known rug history: 0.90
- Factory-deployment pattern: 0.75
- Funded from mixer: 0.65
- New wallet, no history: 0.45 (neutral-ish — not a positive signal)
- Clean established history: 0.15

**Data source:** On-chain transaction history, deployer wallet analysis, cross-reference against known bad-actor lists (where available).

**Missing data policy:** If deployer history is unavailable, apply default risk of 0.50.

---

### Category 2: Holder Concentration Risk (Weight: 0.25)

**What it evaluates:** How concentrated is token ownership? High concentration means a small number of wallets can disproportionately impact price.

**Signals:**

| Metric | Risk Contribution |
|---|---|
| Top 5 wallets hold > 70% of supply | Critical |
| Top 5 wallets hold 50–70% | High |
| Top 5 wallets hold 30–50% | Medium |
| Top 5 wallets hold < 30% | Low |
| Single wallet holds > 20% | High regardless of total |
| Concentration partially from locked/vesting wallets | Reduces risk proportionally |

**Scoring:**
```
concentration_score = clip(top5_pct / 70, 0, 1)
```

Where `top5_pct` is the percentage held by the top 5 wallets (excluding known DEX/pool wallets and locked vesting contracts).

**Caveat:** Very new tokens naturally have high concentration because trading hasn't distributed supply. Time-weight the interpretation: high concentration at T+0 is less alarming than high concentration at T+2h.

---

### Category 3: Wallet Clustering Risk (Weight: 0.20)

**What it evaluates:** Are the token holders independent actors or coordinated wallets from the same source?

**Why this matters:** A token with 500 holders sounds distributed until all 500 were funded from the same 3 wallets in the same block. This is common in "manufactured distribution" strategies.

**Signals:**

| Pattern | Risk Contribution |
|---|---|
| Many holders funded from the same source wallet | High |
| Holders created in the same block or very close time window | High |
| Holder wallets with no other transaction history | Medium |
| Circular fund flow (A→B→C→D all related) | High |
| Holders from diverse, established wallets | Reduces risk |

**Detection method:** Graph analysis of wallet funding paths. Each holder's wallet is traced back N hops to identify common ancestor wallets.

**Scoring:**
- Cluster coefficient > 0.70: score 0.85
- Cluster coefficient 0.50–0.70: score 0.65
- Cluster coefficient 0.30–0.50: score 0.45
- Cluster coefficient < 0.30: score 0.20

**Limitations:** Full graph analysis is computationally intensive. For initial scoring, use heuristics (% of holders funded in same time window, top ancestor wallet count). Full analysis for high-potential tokens only.

---

### Category 4: Liquidity Risk (Weight: 0.15)

**What it evaluates:** Is there enough liquidity for the token to be traded, and is it structured to prevent removal?

**Signals:**

| Signal | Risk Contribution |
|---|---|
| Liquidity entirely unlocked | High |
| Liquidity provided by single wallet | High (single point of removal) |
| Very low total liquidity (< $5K USD equivalent) | High |
| Liquidity locked with time lock < 24 hours | Medium |
| Liquidity locked > 30 days | Low |
| Liquidity from multiple independent providers | Reduces risk |

**Scoring:**
```
liquidity_score = liquidity_risk_factors_weighted_average
```

Where each factor above contributes proportionally.

**Note:** On Pump.fun's bonding curve, the liquidity model differs from standard AMM pools. The Pump.fun graduation event (reaching full bonding curve) is itself a liquidity event. Model appropriately.

---

### Category 5: Contract Anomaly Risk (Weight: 0.10)

**What it evaluates:** Does the token contract have dangerous authorities or unusual patterns?

**Signals:**

| Signal | Risk Contribution |
|---|---|
| Mint authority not renounced | High |
| Freeze authority enabled | High |
| Upgrade proxy with active admin | High |
| Unusual transaction fee structure | Medium |
| Non-standard contract patterns | Medium |
| Renounced/burned authorities | Reduces risk |

**Note:** On Solana/Pump.fun, standard token programs have known patterns. Deviations from standard patterns are suspicious by default.

---

## Combining Category Scores

```
rug_risk_score = (deployer × 0.30) 
               + (concentration × 0.25) 
               + (clustering × 0.20) 
               + (liquidity × 0.15) 
               + (contract × 0.10)
```

**Range:** [0.0, 1.0]

---

## Risk Tiers

| Tier | Score Range | Interpretation |
|---|---|---|
| Low | 0.0–0.30 | Few observable risk signals. Proceed with normal caution. |
| Medium | 0.30–0.55 | Notable risk signals. Warrants close attention. |
| High | 0.55–0.75 | Multiple strong risk signals. Significant caution required. |
| Critical | 0.75–1.0 | Extreme risk indicators. Most tokens in this tier fail. |

**All tiers, including Low, are still risky.** Memecoins as a category are inherently high-risk. "Low" rug risk means fewer observable red flags — not that the investment is safe.

---

## Missing Data Policy

When data for a risk category is unavailable:

| Category | Default Score | Rationale |
|---|---|---|
| Deployer Risk | 0.50 | Unknown deployer = unknown risk |
| Concentration | 0.55 | Assume concentrated until proven otherwise |
| Clustering | 0.50 | Cannot assess without data |
| Liquidity | 0.60 | Unknown liquidity = assume fragile |
| Contract | 0.50 | Cannot assess without code review |

Missing data is not neutral. It is treated as weak-to-moderate risk because bad actors actively obscure information.

---

## What This Framework Cannot Detect

**Sophisticated coordinated rugs** where:
- Deployer uses multiple clean wallets with established history
- Liquidity appears genuine and multi-party
- Clustering is deliberately obfuscated
- Exit happens over hours/days rather than a single transaction

The framework makes cheap rugs easy to detect. Expensive, well-planned rugs are harder. This limitation is acknowledged and cannot be fully resolved.

**Implication:** Even a token with rug_risk_score = 0.20 can still be rugged by a sophisticated actor. Never claim a token is "safe." Always surface the rug_risk_score prominently in alerts.
