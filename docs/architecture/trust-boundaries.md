# Trust Boundaries

This document defines what is trusted, what is verified, what is untrusted, and how the system handles data from adversarial or unreliable sources.

---

## Core Principle

**Assume all external data is potentially adversarial or incorrect until corroborated.**

This is not paranoia — it is the correct posture for this domain. Pump.fun tokens operate in an environment where:
- Social engagement is routinely purchased
- On-chain volume can be washed
- Copycat tokens deliberately mimic canonical names
- News and social posts about tokens are frequently seeded by insiders
- Holder counts can be inflated through airdrops to useless wallets

The trust model must account for this at every input boundary.

---

## Trust Tiers

### Tier 1: High Corroboration Required (Untrusted)

Sources in this tier are used as signals but never accepted as facts. Every claim from these sources requires corroboration from at least one independent source.

| Source Category | Risk | Why |
|---|---|---|
| Token's own Telegram/Discord | Very high | Operator-controlled. All positive signals are suspect. |
| Anonymous Twitter/X accounts | High | Easy to manufacture. Bot farms common. |
| Pump.fun internal metrics (volume, holders) | Medium-High | Can be wash traded. Use as directional only. |
| Token metadata (name, description, image) | High | Trivially fabricated by deployer. |
| News articles citing anonymous sources | High | Common in crypto media. |

**Handling:** Accept signal, apply heavy discount, require corroboration from Tier 2 or higher before using in scoring.

---

### Tier 2: Moderate Trust (Verify Then Use)

Sources that provide meaningful signal but are not immune to manipulation or error.

| Source Category | Risk | Why |
|---|---|---|
| On-chain transaction data | Medium | Raw chain data is accurate, but interpretation is manipulable (wash trading, coordinated wallets) |
| Mainstream crypto media (CoinDesk, The Block, etc.) | Medium | Generally accurate reporting but can amplify seeded narratives |
| Search trends (e.g. Google Trends) | Low-Medium | Hard to fake at scale, but can be gamed with coordinated clicking |
| Known-good social accounts with track record | Low-Medium | History-verified but still can be compromised |

**Handling:** Use directly in scoring with standard weights. Flag when signal contradicts Tier 1 data.

---

### Tier 3: Relatively Trusted (Use with Standard Skepticism)

| Source Category | Risk | Why |
|---|---|---|
| On-chain deployer history (historical patterns) | Low | Historical on-chain data is immutable and accurate |
| Mainstream non-crypto news sources | Low | Covering real-world events, not crypto specifically |
| Holder wallet clustering analysis (using multiple signals) | Low-Medium | Cross-signal approach reduces individual signal manipulation risk |

**Handling:** Use at full weight in scoring. Still flag anomalies.

---

## Adversarial Handling Rules

### Rule 1: Never Trust Single-Source Social

A token with 10,000 Telegram members and no other external signals is not validated. The members may be paid. The volume may be washed. A single-source positive signal is a red flag, not a green flag.

**Implementation:** Attention scores derived from a single source receive a corroboration penalty. See `docs/intelligence/momentum-analysis.md`.

---

### Rule 2: On-Chain Data Is Accurate but Not Sufficient

The blockchain records are accurate. But what they record can be engineered. A token with 5,000 holders all funded from the same source wallet is technically accurate on-chain and still suspicious.

**Implementation:** Chain data is read accurately but interpreted with clustering and pattern analysis. Raw holder count alone is not a valid signal without wallet clustering analysis.

---

### Rule 3: Name Similarity Is Not Narrative Match

A token named "GEMINI" during a Google AI news cycle may or may not be narratively relevant. Name overlap is a starting signal, not a conclusion. The correlation engine must produce match signals, not just a match/no-match binary.

**Implementation:** All name matches include a `match_signals[]` array explaining what matched and why.

---

### Rule 4: Deployer-Originated Signals Are Discounted

Anything that can be set by the token's deployer is untrusted by default:
- Token name and symbol
- Token description
- Links in metadata
- Initial holder list (if airdropped)
- Social channels listed in metadata

**Implementation:** Deployer-controlled data is flagged in the record schema. It is used for name matching but carries no weight in trust-based scoring.

---

### Rule 5: Corroboration Increases Trust, Agreement Does Not

Two Telegram accounts saying the same thing is not corroboration — it may be the same actor with two accounts. True corroboration requires:
- Different source types (social + news + search trends)
- Sources that are independent (not the same network or operator)
- Signal consistency across time (not just a single coordinated moment)

**Implementation:** The corroboration scoring function checks source type diversity, not just source count.

---

### Rule 6: LLM Outputs Are Treated as Tier 1

When an LLM is used (e.g., for semantic narrative matching), its output is treated as an untrusted signal. It must be validated against structured data before being used to increase scores.

**Implementation:** See `docs/implementation/agent-strategy.md` for LLM usage constraints.

---

## Trust Boundary Enforcement Points

| Boundary | Enforcement |
|---|---|
| Raw source → Normalized record | Normalizer validates types, rejects malformed, logs anomalies |
| Normalized record → Scoring input | Scoring engine checks data age, source tier, and corroboration before weighting |
| LLM output → System signal | LLM output validated against structured constraints before use |
| Alert output → Delivery | Alert includes all trust signals and data gaps; delivery layer does not strip them |
| External webhook / push → System | All incoming data treated as untrusted until processed through normalization pipeline |

---

## What the System Cannot Defend Against

**Sophisticated coordinated manipulation across multiple independent-looking sources** (so-called "astroturfing at scale") is very hard to detect reliably. A well-resourced actor who:
- Buys legitimate press coverage
- Seeds genuine-looking social discussion across many accounts
- Creates genuine search interest through coordinated effort
- Is the first to launch a legitimate-looking token

...may successfully fool the scoring system. This is an acknowledged limitation. The system makes manipulation harder and more expensive, not impossible.

**Implication:** High-confidence scores do not guarantee the signal is authentic. Confidence reflects evidence quality, not integrity. This limitation must be communicated to users.
