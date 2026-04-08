# Momentum Analysis

This document defines how the system distinguishes organic momentum from manipulated or artificial activity.

---

## Why Momentum Quality Matters

In the memecoin market, volume and price movement can be engineered. A token can show impressive charts while being entirely controlled by a small group executing a pump-and-dump. A system that treats all volume as equal will produce false signals.

Momentum quality assessment does not predict future price. It estimates whether the current momentum has characteristics consistent with organic participation, or characteristics consistent with coordinated manipulation.

High-quality organic momentum tends to:
- Sustain longer as new genuine participants join
- Correlate with external narrative attention (people are talking about it outside crypto)
- Come from many diverse wallets making many small trades
- Show gradual growth patterns rather than vertical spikes

Manufactured momentum tends to:
- Spike sharply then die or slowly bleed
- Show high volume from few wallets
- Not correlate with external attention
- Involve coordinated wallet behavior

---

## Momentum Quality Dimensions

### Dimension 1: Volume Pattern Quality (Weight: 0.30)

**Definition:** Does the volume growth pattern resemble organic discovery, or does it look like a coordinated event?

**Organic patterns:**
- Gradual increasing volume over 30–120 minutes
- Multiple volume waves as different participant groups discover the token
- Volume sustained or growing even as early wallets exit

**Suspicious patterns:**
- Single sharp volume spike followed by collapse
- Volume appearing in a very narrow time window (< 5 minutes of extreme activity)
- Volume that stops abruptly rather than decaying

**Scoring approach:**
- Measure volume over time in rolling windows (5m, 15m, 30m, 1h)
- Compute the ratio of peak-window volume to average-window volume
- High ratios (> 10x peak vs. average) indicate spike patterns
- Low ratios (< 3x) suggest more distributed activity

**Heuristic:**
```
pattern_score = 1 - clip((peak_5m_volume / avg_30m_volume - 1) / 15, 0, 1)
```

A single 5-minute window responsible for 16x the average is suspicious (score approaches 0). Distributed activity scores close to 1.

---

### Dimension 2: Trade Diversity (Weight: 0.30)

**Definition:** Are many independent wallets trading, or is volume dominated by a few?

**Organic indicators:**
- High unique buyer count relative to trade count
- Relatively even distribution of trade sizes
- Buyers coming from diverse wallet origins (not all funded from same source)

**Suspicious indicators:**
- Top 5 traders account for > 50% of volume
- Large number of identical or very similar trade sizes (suggests automation)
- Wallets trading the same token back and forth between known associates

**Metrics:**

| Metric | Definition |
|---|---|
| `unique_buyer_ratio` | unique_buyers / total_trades (higher = better) |
| `volume_concentration` | volume from top 5 wallets / total volume |
| `trade_size_entropy` | distribution entropy of trade sizes (higher = more diverse) |

**Scoring:**
```
diversity_score = (1 - volume_concentration) × 0.60 + unique_buyer_ratio × 0.40
```

---

### Dimension 3: Social-Chain Alignment (Weight: 0.20)

**Definition:** Does on-chain activity timing correlate with social narrative timing, or does the on-chain activity precede any social signal?

**Organic pattern:** Social attention (external discussion, search interest) happens first or simultaneously with on-chain activity. People hear about something → look it up → trade.

**Suspicious pattern:** On-chain activity precedes social signal by significant margin, or on-chain activity has no associated social signal at all. This suggests insiders trading before public awareness.

**Measurement:**
- Compare timestamp of first meaningful volume (> X trades) vs. timestamp of first external social signal for this specific token
- Measure cross-correlation over time window

**Scoring:**
```
if social_signal_precedes_volume_by <= 60 minutes:
    alignment_score = 1.0
elif volume_precedes_social_by <= 30 minutes:
    alignment_score = 0.6  # possible but not typical organic
elif volume_precedes_social_by > 30 minutes:
    alignment_score = 0.2  # insider activity pattern
elif no_social_signal:
    alignment_score = 0.3  # suspicious absence
```

**Caveat:** This signal requires that social data is available. If social data is missing, alignment score defaults to 0.5 (neutral) and confidence is reduced.

---

### Dimension 4: Holder Growth Pattern (Weight: 0.20)

**Definition:** Is the holder count growing in an organic pattern, or does it show mass-add events typical of airdrop farming or sybil generation?

**Organic indicators:**
- Steady incremental holder growth
- New holders arriving over time as trading occurs
- Holder wallets have prior transaction histories

**Suspicious indicators:**
- Large batch of new holders appearing in a single block or minute
- New holders with no prior history (freshly created wallets)
- Holder count spikes without corresponding organic volume

**Metrics:**
- `holder_growth_rate`: new holders per hour
- `batch_add_events`: count of time windows where > 20 wallets are added in < 60 seconds
- `new_wallet_pct`: percentage of holders whose wallets are < 24 hours old

**Scoring:**
```
holder_quality_score = 1 - (batch_add_events × 0.15 + new_wallet_pct × 0.85)
                       bounded to [0, 1]
```

---

## Combining Momentum Dimensions

```
momentum_quality = (volume_pattern × 0.30) + (diversity × 0.30) + (alignment × 0.20) + (holder_growth × 0.20)
```

**Range:** [0.0, 1.0]

| Score | Interpretation |
|---|---|
| 0.0–0.25 | Strong manipulation signals. Activity is likely engineered. |
| 0.25–0.45 | Suspicious patterns present. Mixed signals. |
| 0.45–0.65 | Moderate quality. Some organic indicators but not clean. |
| 0.65–0.80 | Reasonably organic momentum pattern. |
| 0.80–1.0 | Strong organic indicators across all dimensions. |

---

## Limitations and Failure Modes

**Wash trading detection:** The system uses heuristics for wash trading detection, not a rigorous graph analysis. Sophisticated wash trading (using many unrelated-looking wallets with established history) can fool these heuristics.

**Social data gaps:** If social data is unavailable, the alignment dimension defaults to neutral, reducing the ability to distinguish organic from coordinated.

**Small sample size:** Very new tokens with few trades produce unreliable momentum scores. Scores should be weighted less heavily for tokens with < 50 trades.

**Airdrop farming detection:** Some organic tokens do receive large airdrops from legitimate projects. Large batch-holder events are suspicious but not always fake. Context matters.

**The absence of manipulation signals is not proof of organic activity.** The system identifies suspicious patterns when present; it cannot prove their absence.

---

## Momentum vs. Price

Momentum analysis evaluates the quality of market activity — not price level, not whether the token is "up." A token with high-quality momentum at a stable price is more interesting than a token with suspicious momentum at a 10x price.

Do not conflate momentum quality with directional price analysis. The system does not do price analysis.
