# Scoring Model

This document defines the six evaluation dimensions, how each is computed, and how they combine into the final probability estimates.

Full mathematical treatment is in `docs/intelligence/probability-framework.md`. This document focuses on what each dimension means and how it is evaluated.

---

## Overview

Every token candidate is evaluated across six dimensions:

| # | Dimension | What It Measures |
|---|---|---|
| 1 | Narrative Relevance | Does this token actually connect to a real-world trend/event? |
| 2 | Authenticity / OG Likelihood | Is this the original/canonical token or a copycat? |
| 3 | Rug Risk | What is the probability of deployer or structural failure? |
| 4 | Momentum Quality | Is the price/volume activity organic or manipulated? |
| 5 | Attention Strength | How strong is the external narrative driving this? |
| 6 | Timing Quality | Where is this in its lifecycle? Too early, peak, or past it? |

Each dimension produces a score in range [0, 1].

- For dimensions 1, 2, 4, 5, 6: higher = better (more positive signal)
- For dimension 3 (Rug Risk): higher = more risky (feeds into P_failure, not P_potential)

---

## Dimension 1: Narrative Relevance

**What it answers:** Does this token represent a real cultural/news moment, or is it noise?

**Score range:** 0.0 = no plausible connection, 1.0 = strong, multi-source-confirmed connection

### Inputs:
- Token name / symbol
- Active narrative / event records
- Match confidence from correlation engine
- Number and diversity of sources confirming the narrative

### Scoring factors:
- **Name alignment** (0–0.4): How closely does the token name match the trend term? Exact match → high score; tangential match → low score.
- **Narrative recency** (0–0.3): Is the narrative fresh (within hours)? Older narratives decay.
- **Source diversity** (0–0.3): Is the narrative confirmed by multiple independent source types (search + news + social)?

### Example:
Token `$DOGE2` launched during a viral Elon Musk tweet about dogs.
- Name alignment: 0.7 (partial match, not exact)
- Narrative recency: 0.28 (narrative is 2 hours old, still fresh)
- Source diversity: 0.18 (only Twitter signal, no search trends or news)
- Narrative relevance: 0.7*0.4 + 0.28 + 0.18 = 0.74

### Limitations:
- Semantic matching introduces false positives. "DEEPMIND" is a clear match; "THINK" is ambiguous.
- Rapidly decaying narratives may score high at T+0 and become irrelevant by T+2h.
- Ambiguous name → narrative links are marked with low confidence and lower narrative score.

---

## Dimension 2: Authenticity / OG Likelihood

**What it answers:** If multiple tokens match this narrative, which is most likely the original?

**Score range:** 0.0 = almost certainly a copycat, 1.0 = strong OG indicators

### Inputs:
- Token launch time relative to narrative detection time
- Token name match quality vs. other tokens in same namespace
- Cross-source mentions of this specific token (not the narrative generally)
- Deployer wallet history (prior deployments in same narrative space are suspicious)

### Scoring factors:
- **Timing advantage** (0–0.4): First launched within the namespace after narrative emerges.
- **Name precision** (0–0.3): Closest match to canonical narrative term.
- **Independent mentions** (0–0.3): This token specifically mentioned in sources outside its own community.

### Notes:
- Score of 0.5 means "uncertain" — treat as ambiguous, not as probable copycat or probable OG.
- Copycats often have near-identical names to OG. Distinguish by timing and cross-source.
- See full treatment in `docs/intelligence/og-token-resolution.md`.

---

## Dimension 3: Rug Risk

**What it answers:** What is the probability of structural failure, deployer exit, or coordinated abandonment?

**Score range:** 0.0 = low observed risk signals, 1.0 = extreme risk signals

This score feeds into `P_failure`, not `P_potential`. Higher = worse.

### Inputs:
- Deployer wallet history
- Holder concentration (top 5/10/20 wallet percentages)
- Wallet clustering (are holders funded from same source?)
- Liquidity lock status and amount
- Token contract characteristics (mint authority, freeze authority)
- Metadata completeness and quality

### Scoring factors:
- **Deployer risk** (0–0.3): Previous rug deployments, new wallet with no history, abnormal transaction patterns.
- **Concentration risk** (0–0.3): Top wallets hold > 50% of supply with no lock.
- **Liquidity risk** (0–0.2): Unlocked, low, or single-provider liquidity.
- **Contract anomaly** (0–0.2): Unrenounced mint authority, freeze authority, suspicious contract code patterns.

### Notes:
- Missing data in any category: apply conservative default (0.3 for that factor unless other signals suggest otherwise).
- Risk tiers: Low (0–0.3), Medium (0.3–0.6), High (0.6–0.8), Critical (0.8–1.0).
- See full framework in `docs/intelligence/rug-risk-framework.md`.

---

## Dimension 4: Momentum Quality

**What it answers:** Is the market activity around this token organic or artificially inflated?

**Score range:** 0.0 = highly suspicious/manufactured momentum, 1.0 = strong organic signal

### Inputs:
- Volume over time (looking for organic growth pattern vs. spike pattern)
- Trade count vs. volume (many small trades = more organic)
- Holder count growth rate
- Social signal alignment with on-chain activity
- Wallet behavior diversity (are the same wallets responsible for most trades?)

### Scoring factors:
- **Volume pattern quality** (0–0.3): Organic growth curve vs. single-spike pattern.
- **Trade diversity** (0–0.3): Many unique wallets trading vs. few wallets dominating volume.
- **Social-onchain alignment** (0–0.2): Does social momentum match on-chain momentum timing?
- **Holder growth pattern** (0–0.2): Organic holder growth vs. suspicious mass-add events.

### Notes:
- Wash trading is detectable but not perfectly. The presence of suspicious patterns reduces score; absence does not confirm organic.
- See full treatment in `docs/intelligence/momentum-analysis.md`.

---

## Dimension 5: Attention Strength

**What it answers:** How strong is the real-world narrative that the token is riding?

**Score range:** 0.0 = no meaningful external attention, 1.0 = massive multi-source real-world attention

### Inputs:
- Search trend magnitude and velocity
- News article count and outlet quality
- Social discussion volume from non-crypto sources
- Cultural salience indicators (is this in mainstream conversation?)

### Scoring factors:
- **Search magnitude** (0–0.35): Absolute search volume level, normalized.
- **Source breadth** (0–0.35): How many independent source types are covering this narrative?
- **Narrative velocity** (0–0.3): Is attention growing, stable, or declining?

### Notes:
- Attention on the token itself does not count. Attention on the underlying narrative counts.
- A token riding a micro-niche trend will score differently than one riding a global news event.
- Attention decays. Re-score when narrative velocity turns negative.

---

## Dimension 6: Timing Quality

**What it answers:** How well-positioned is this token in its narrative lifecycle?

**Score range:** 0.0 = too late (narrative exhausted or token saturated), 1.0 = very early with runway remaining

### Inputs:
- Time since narrative first detected
- Time since token launched
- Narrative velocity direction (accelerating or decelerating)
- Market saturation (how many tokens in this namespace are active?)

### Scoring factors:
- **Lifecycle position** (0–0.4): Early in narrative lifecycle → high score. Late → low score.
- **Narrative acceleration** (0–0.3): Is the narrative still growing vs. peaked/declining?
- **Market saturation** (0–0.3): Few competing tokens → higher opportunity; dozens of copycats → lower.

### Notes:
- Timing quality is the most volatile dimension. It decays fastest.
- A high score at T+0 can become low by T+2h.
- This is why re-evaluation is critical.

---

## Dimension Score Summary

| Dimension | Feeds Into | Direction | Key Risk |
|---|---|---|---|
| Narrative Relevance | P_potential | Higher is better | False matches, narrative decay |
| Authenticity (OG) | P_potential | Higher is better | Ambiguous OG resolution |
| Rug Risk | P_failure | Higher is worse | Missing data defaults to risk |
| Momentum Quality | P_potential | Higher is better | Wash trading undetected |
| Attention Strength | P_potential | Higher is better | Narrative decay |
| Timing Quality | P_potential | Higher is better | Rapid decay |

---

## Combining Dimensions

Dimension scores feed into `P_potential` and `P_failure`, which combine into `net_potential`.

Full formula and weights are in `docs/intelligence/probability-framework.md`.

**The weights are configurable, not hardcoded.** Initial weights are set as documented starting points. They should be tuned as calibration data accumulates.
