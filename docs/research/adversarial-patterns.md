# Adversarial Patterns

This document catalogs known manipulation, scam, and copycat patterns. Understanding these patterns is essential for building detection logic that actually works.

This is a living document. Add patterns as they are encountered or researched.

---

## Pattern Category 1: Rug Pull Variants

### 1a. Instant Liquidity Rug

**Description:** Deployer adds liquidity, token launches, deployer immediately removes all liquidity in the same or next block.

**On-chain signature:**
- Liquidity add → remove in < 5 minutes
- Often at unusual hours or during high-traffic periods to avoid notice
- Deployer wallet funded and emptied rapidly

**Detection:**
- Monitor for liquidity removal events linked to token deployer wallet
- Flag if liquidity decreases > 50% within 60 minutes of launch
- Cross-reference liquidity provider wallet against deployer wallet

**False positive risk:** Some liquidity rebalancing events look similar. Check if liquidity is replaced vs. simply removed.

---

### 1b. Slow Rug

**Description:** Deployer gradually removes liquidity over hours or days. Avoids single large event that triggers immediate alerts.

**On-chain signature:**
- Steady decline in liquidity pool size over 12–48 hours
- Deployer wallet shows small, regular outflows
- Price chart shows slow consistent decline rather than sudden drop

**Detection:**
- Track liquidity trend over time, not just spot checks
- Flag when liquidity has declined > 40% from peak over any 24-hour window
- Re-evaluation scheduler is critical for this — it must catch slow-moving deterioration

**Difficulty:** Harder to detect than instant rug. Threshold for triggering a re-evaluation must be sensitive enough to catch this.

---

### 1c. Soft Rug (Insider Dump)

**Description:** Deployer or insiders (pre-loaded wallets) hold a large supply percentage and dump once the retail price is elevated.

**On-chain signature:**
- High holder concentration at launch (top 5 wallets > 50%)
- Price spike followed by concentrated sell orders from early wallets
- Often the deployer wallet itself is not the seller — associated wallets are

**Detection:**
- Holder concentration risk (Category 2 in rug risk framework)
- Wallet clustering analysis to identify insider-associated wallets
- Monitor early wallet sell activity for concentrated dumps

**Note:** This is the hardest rug to detect pre-fact. It looks clean on contract analysis. The concentration signal is the primary early warning.

---

### 1d. Mint Authority Abuse

**Description:** Deployer mints a large additional supply after launch and dumps it on the market.

**On-chain signature:**
- `MintTo` instruction from deployer wallet after initial launch
- Supply increases unexpectedly
- Price collapses as new supply hits the market

**Detection:**
- Flag tokens with active mint authority (Contract Anomaly Risk, Category 5)
- Monitor for supply changes post-launch
- Alert immediately on any post-launch `MintTo` event

**Critical:** Active mint authority is a non-negotiable risk flag. It must always appear in alerts as a prominently visible risk.

---

## Pattern Category 2: Copycat / Namespace Attacks

### 2a. Shotgun Copycat

**Description:** A single actor deploys dozens of tokens with slight name variations when a narrative emerges, hoping one gains traction.

**On-chain signature:**
- Multiple tokens deployed from same wallet or wallet cluster within short time window
- Token names all variations of same anchor term
- All tokens have similar initial liquidity from same source

**Detection:**
- Deployer pattern analysis: detect multiple deployments from same wallet
- Namespace collision detection: multiple tokens in same namespace from same deployer

**Goal of this pattern:** Capture the narrative even if the "real" token gets more attention. Spreads confusion.

---

### 2b. Late Precision Copycat

**Description:** A single actor waits to see which token in a namespace gains traction, then deploys an exact-name copy to confuse new buyers.

**On-chain signature:**
- Token with identical or near-identical name to an already-active token
- Launched significantly later (hours, not minutes)
- May have better initial liquidity to appear more legitimate

**Detection:**
- Namespace collision detection: flag any token that enters a namespace after an established OG
- Temporal priority signal in OG resolver strongly penalizes late entrants

**Risk:** New buyers searching for the OG token may find and buy the copycat instead.

---

### 2c. Narrative Hijack

**Description:** A token that already exists (unrelated to any narrative) rebrands its social presence to claim it is the official token of an emerging narrative.

**On-chain signature:**
- Token launch time doesn't align with narrative emergence
- Token name may not match the narrative anchor (rebranding happens in social, not on-chain)
- Cross-source social signals mention the token as relevant to the narrative, but the timing is suspicious

**Detection:**
- Temporal priority signal: token launch time vs. narrative detection time
- If launch time > 6 hours before narrative detection, flag as potential hijack
- Monitor for sudden narrative-adjacent social activity on old/previously inactive tokens

**Difficulty:** This pattern can fool narrative matching if we only look at social signals. Timing signals are critical.

---

## Pattern Category 3: Manufactured Momentum

### 3a. Wash Trading

**Description:** Same actor (or actor cluster) buys and sells to each other to create apparent volume, making the token appear more active than it is.

**On-chain signature:**
- Circular trade flow: A→B→A, or A→B→C→A
- Identical or near-identical trade sizes
- Trades at regular intervals (bots)
- Volume concentrated in few wallets

**Detection:**
- Volume concentration analysis (Dimension 4: Trade Diversity)
- Circular flow detection (requires wallet graph analysis)
- Trade size entropy analysis (low entropy = suspicious uniformity)

**Difficulty:** Sophisticated wash traders use many wallets with varied sizes. Basic analysis catches naive implementations.

---

### 3b. Coordinated Buy-Wall

**Description:** Coordinated wallets place large buy orders simultaneously to create the appearance of demand, attracting retail buyers before insiders exit.

**On-chain signature:**
- Large coordinated buys appearing in same block or consecutive blocks from multiple wallets
- Wallets funded from similar sources
- Buy wall is later removed or filled, triggering price collapse

**Detection:**
- Holder growth pattern analysis: batch additions from coordinated wallets
- Wallet clustering: are these buying wallets related?

---

### 3c. Social Bot Amplification

**Description:** Purchased bot accounts amplify token-related posts to make the token appear more viral than it is.

**Signal:**
- Engagement on token posts comes heavily from new or low-history accounts
- Engagement rates are anomalously high vs. typical for similar content
- Bot-like patterns: all engagements happen within seconds of posting

**Detection:**
- Bot percentage estimation in social data
- Account age and history signals
- Engagement timing distribution analysis

**Limitation:** Sophisticated bot campaigns use aged accounts with established histories. These are very hard to detect without platform-level signals.

---

## Pattern Category 4: Meta-Manipulation

### 4a. Scoring System Gaming

**Description:** Bad actors attempt to engineer signals specifically to fool this system's scoring model.

**What this would look like:**
- Ensuring the token name exactly matches a trending narrative (to score high on narrative relevance)
- Using a fresh but clean-looking deployer wallet (to avoid deployer risk flags)
- Timing the launch to appear early in the narrative lifecycle
- Creating artificial cross-source token mentions to boost OG score

**Why this is possible:** This system's general architecture and scoring signals are described in public documentation. A sophisticated actor can study it and design against it.

**Mitigations:**
- No single dimension is decisive — gaming one requires gaming all
- Cross-source validation requires fabricating signals on genuinely independent platforms — expensive
- Temporal signals are hard to fake (you can't retroactively make a token appear earlier)
- Wallet history takes real time to build authentically

**Honest acknowledgment:** Sufficiently motivated and resourced actors can fool this system. The system makes it expensive and difficult, not impossible. This limitation cannot be fully resolved.

---

## Detection Confidence Calibration

Not all adversarial patterns are detectable with the same confidence:

| Pattern | Detection Confidence | Primary Signal |
|---|---|---|
| Instant liquidity rug | High | On-chain event (clear and fast) |
| Mint authority abuse | High | Contract flag + post-launch mint event |
| Shotgun copycat | High | Same-deployer namespace pollution |
| Slow rug | Medium | Liquidity trend tracking |
| Soft rug / insider dump | Medium | Holder concentration + sell monitoring |
| Wash trading (naive) | Medium | Volume concentration |
| Late precision copycat | Medium | Timing + namespace collision |
| Wash trading (sophisticated) | Low | Graph analysis needed |
| Social bot amplification (sophisticated) | Low | Limited signals |
| Narrative hijack | Low | Temporal analysis |
| Scoring system gaming | Very low | Designed to evade detection |

**Implication:** High-confidence rug patterns → `discard`. Low-confidence manipulation patterns → increase risk flags and reduce confidence score, but do not automatically discard.
