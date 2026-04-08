# OG Token Resolution

This document defines how the system estimates whether a token is the original, canonical token for a given narrative — or a copycat.

---

## Why This Matters

When a real-world narrative trend emerges, dozens of tokens are typically launched within minutes, all with names referencing the same event. Nearly all are opportunistic copies. At most one (sometimes zero, occasionally more) represents the token that the community organically rallied around.

The "OG" token — the original, canonical token for a given narrative — tends to:
- Capture the majority of organic trading attention
- Be referenced in social discussion by name
- Retain value longer if the narrative sustains
- Be the token that gets mentioned in external channels (crypto media, influencers, X posts)

Copycats typically:
- Launch minutes after the OG and after several others
- Use slightly modified names (DEEPMIND → DMIND → DEEP)
- Have no cross-source mentions of the specific token address
- Often exit quickly once the OG is identified by the market

**The system's goal is not to guarantee correct OG identification.** It is to rank candidates by estimated OG likelihood and communicate that uncertainty.

---

## OG Resolution Process

OG resolution is triggered when two or more tokens are linked to the same narrative.

### Step 1: Build the Candidate Set

All `TokenNarrativeLink` records for the same narrative form the candidate set. Each token in the set becomes a candidate.

### Step 2: Score Each Candidate Across OG Signals

Each candidate is evaluated on four signal categories:

---

#### Signal 1: Temporal Priority (Weight: 0.35)

**Definition:** Which token was launched first, relative to when the narrative was first detected?

**Scoring logic:**
- First token to launch: full temporal priority score (1.0)
- Each subsequent token: reduced by delay factor

```
temporal_score = max(0, 1 - (minutes_after_first / DECAY_CONSTANT))
```

`DECAY_CONSTANT` is configurable (default: 30 minutes). A token launched 30 minutes after the first gets a temporal score of 0.0. A token launched 5 minutes after the first gets approximately 0.83.

**Caveat:** The first token is not always the OG. Sophisticated actors sometimes launch fakes immediately to pollute the namespace before the community-identified OG launches. Temporal priority is a signal, not a determination.

---

#### Signal 2: Name Precision (Weight: 0.25)

**Definition:** How precisely does the token name match the canonical narrative anchor term?

**Scoring logic:**

| Match Type | Score |
|---|---|
| Exact match to primary anchor term | 1.0 |
| Exact match to secondary anchor term | 0.80 |
| Abbreviation of primary anchor term | 0.65 |
| Token name contains anchor term | 0.50 |
| Token name semantically related | 0.30 |
| Token name tangentially related | 0.15 |

**Tie-breaking:** In a namespace where multiple tokens have the same exact match quality (e.g., three tokens all named `$DEEPMIND`), name precision cannot differentiate. Other signals take priority.

---

#### Signal 3: Cross-Source Token Mentions (Weight: 0.30)

**Definition:** Is this specific token (by address or by name + chain combo) being discussed in independent external sources?

This is the strongest OG signal when present, because copycats rarely get independently mentioned.

**Scoring logic:**
```
cross_source_score = min(unique_source_mention_count / MAX_EXPECTED_MENTIONS, 1.0)
```

`MAX_EXPECTED_MENTIONS` is configurable (default: 5 unique mentions from 3+ different source types = score of 1.0).

Source types that count:
- Crypto media articles mentioning the specific token
- Verified influencer posts naming the token specifically (not just the narrative)
- Search trends showing the token's ticker as a search term
- Cross-community discussion (e.g., token mentioned on Reddit AND Twitter, not just one)

Source types that do NOT count:
- The token's own Telegram/Discord
- Posts from the deployer wallet's associated accounts
- Pump.fun's own listing metrics

---

#### Signal 4: Deployer Pattern (Weight: 0.10)

**Definition:** Does the deployer's on-chain history suggest this is a thoughtful launch or a quick copy-deploy?

**Scoring logic:**
- New wallet, first token launched → neutral (0.5) — could be anyone
- Wallet with history of deploying in same narrative space as other launches → lower score (0.2)
- Wallet with established positive history → higher score (0.8)

**Note:** Deployer pattern is the weakest OG signal because sophisticated deployers use fresh wallets for OG launches intentionally (privacy). Do not over-weight this signal.

---

### Step 3: Compute OG Score

```
og_score = (temporal × 0.35) + (name_precision × 0.25) + (cross_source × 0.30) + (deployer × 0.10)
```

### Step 4: Rank Candidates

Sort candidates descending by `og_score`. Assign `og_rank` (1 = most likely OG).

---

## Interpreting OG Scores

| Score | Interpretation |
|---|---|
| 0.80–1.0 | Strong OG indicators. High confidence this is the canonical token. |
| 0.60–0.79 | Probable OG. Meaningful advantage over competitors. |
| 0.40–0.59 | Uncertain. Insufficient evidence to distinguish OG from copycat confidently. |
| 0.20–0.39 | Probable copycat. Likely a late-entry opportunistic token. |
| 0.0–0.19 | Strong copycat indicators. Very unlikely to be the canonical token. |

---

## Naming Collision Handling

Sometimes multiple legitimate tokens share a name because the name is a common word or abbreviation:

- `$AI` is a valid ticker for thousands of narratives involving AI
- `$PEPE` was used before and independently of the specific frog meme narrative

**How to handle:**
1. Treat tokens with generic names as having lower name precision scores
2. Require more cross-source evidence before elevating an OG score
3. Flag the token as `namespace_collision_risk` in the record
4. Do not suppress the token — continue scoring with noted caveat

---

## Ambiguity Cases

### Zero-Strong-Signal Namespace
All tokens in a narrative namespace have low cross-source mentions and similar launch times. No clear OG.

**Response:** All tokens marked `og_ambiguous`. OG score range 0.35–0.55 for all candidates. All receive this flag in their alert. No token is elevated as probable OG.

### Late-But-Community-Adopted Token
A token launches 2 hours after the first-mover but then receives strong community adoption and cross-source mentions. The first-mover had no cross-source traction.

**Response:** Cross-source signal (weight 0.30) should eventually elevate the late launcher's score above the early launcher's. This is why continuous re-evaluation is required — OG scores are not fixed at launch time.

### Multiple Tokens Both Have High OG Scores
Two tokens both score > 0.70.

**Response:** Treat both as probable OG candidates. Both receive alerts noting "competitive OG namespace." Neither is suppressed. Human judgment is required for this case.

---

## What OG Resolution Is Not

- It does not guarantee that the identified OG is "good" or "safe"
- It does not predict which token the market will ultimately prefer
- It does not eliminate rug risk for the probable OG
- It is not a deterministic classification — it is a probabilistic ranking

An OG score of 0.85 means "strong OG indicators." It does not mean "this is definitely the canonical token."
