# Source Types

This document defines the taxonomy of data source categories, their trust profiles, freshness expectations, and what each contributes to the system.

---

## Source Category Overview

| Category | What It Provides | Trust Tier | Typical Freshness |
|---|---|---|---|
| On-Chain (Solana) | Token events, transactions, holder data | Tier 2–3 | Seconds to minutes |
| Token Launch Platforms | New token metadata, early metrics | Tier 2 | Seconds to minutes |
| Search Trends | Narrative attention measurement | Tier 2 | 15–60 minutes lag |
| Mainstream News | Real-world narrative detection | Tier 2 | Minutes to hours |
| Crypto-Native News | Token and market signals | Tier 2 | Minutes |
| Social Platforms (Public) | Social attention, community signals | Tier 1 | Real-time to minutes |
| Community Channels | Token-specific community activity | Tier 1 (highly suspect) | Real-time |
| Cross-Reference Lists | Known bad actors, flagged wallets | Tier 3 | Periodic updates |

---

## Source Category: On-Chain (Solana)

**What it provides:**
- Token contract creation events (new token detection)
- Transaction history (volume, trade count, unique traders)
- Holder distribution at a point in time
- Deployer wallet address and its history
- Liquidity pool state (amount, lock status, provider composition)
- Contract-level data (mint authority, freeze authority)

**Trust profile:**
- The chain data itself is accurate and immutable
- However, what it records can be engineered (wash trades, coordinated wallets, airdrop inflation)
- On-chain data is Tier 2: accurate source, interpretable under adversarial conditions

**Freshness:**
- Block-level data: seconds latency
- Aggregated metrics (holder count, volume): may lag by 1–5 minutes depending on indexing

**Limitations:**
- Requires a reliable RPC endpoint or indexing service
- High-frequency polling is expensive; rate limits apply
- Historical data beyond recent blocks may require archive node access

**Critical signals this source enables:**
- Token discovery (new launch detection)
- Rug risk assessment (deployer, holder concentration, liquidity)
- Momentum analysis (trading patterns, wallet diversity)

---

## Source Category: Token Launch Platforms

**What it provides:**
- Real-time feed of new token launches on Pump.fun
- Token name, symbol, description, social links
- Launch configuration (initial supply, initial price, bonding curve parameters)
- Early trading metrics from the platform

**Trust profile:**
- Metadata is provided by the deployer and is not independently verified — Tier 1
- Launch event timing and on-chain parameters are accurate — Tier 2

**Freshness:**
- Real-time via websocket or near-real-time via polling

**Limitations:**
- Metadata (name, description, social links) is deployer-controlled and cannot be trusted
- Platform APIs may have rate limits or require authentication
- Platform-specific changes (contract upgrades, fee structure changes) may affect data interpretation

**Critical signals this source enables:**
- Primary token discovery trigger
- Initial metadata for name/narrative matching

---

## Source Category: Search Trends

**What it provides:**
- Real-time trending topics by search volume
- Relative popularity of specific search terms over time
- Geographic distribution of search interest

**Trust profile:**
- Difficult to fake at meaningful scale — Tier 2
- Reflects genuine public curiosity but can be gamed with coordinated searching at small scale

**Freshness:**
- Typically 15–60 minute lag in publicly available APIs
- Some providers offer more recent data at higher cost/complexity

**Limitations:**
- Does not directly indicate crypto relevance — a trending search term may have nothing to do with a token launch
- Very short-lived micro-trends may be missed between polling intervals
- API rate limits and data freshness constraints vary by provider

**Critical signals this source enables:**
- Narrative strength measurement (is anyone actually searching for this?)
- Narrative lifecycle detection (is interest growing, peaking, declining?)
- External validation of social signals

---

## Source Category: Mainstream News

**What it provides:**
- Published articles from established news outlets
- Real-world events that may correlate with memecoin narratives
- Named entities (people, companies, products) in the news cycle

**Trust profile:**
- Generally accurate reporting — Tier 2 to Tier 3
- Crypto-related news in mainstream outlets has higher quality bar than crypto-native media

**Freshness:**
- Minutes to hours depending on indexing and API polling

**Limitations:**
- Coverage is not real-time; some narrative moments happen faster than articles are published
- Named entity extraction requires reliable NLP; errors will produce false narrative matches
- Paywalled content may not be accessible

**Critical signals this source enables:**
- Narrative detection for major events
- High-quality corroboration of narratives seen in social signals
- Named entity extraction for anchor terms used in correlation

---

## Source Category: Crypto-Native News

**What it provides:**
- Coverage of crypto-specific events, launches, and trends
- Sometimes the first published coverage of a narrative entering crypto context
- Mentions of specific tokens or deployers

**Trust profile:**
- Quality varies widely — Tier 1 to Tier 2
- Crypto media has historically published articles seeded by promoters
- Discounting required: crypto media coverage alone is not strong corroboration

**Freshness:**
- Minutes for breaking news

**Limitations:**
- High bias risk — crypto media is economically incentivized to cover certain projects
- Promotional vs. editorial coverage is not always distinguishable
- Some outlets have poor factual accuracy on specific token details

**Critical signals this source enables:**
- Early narrative detection within the crypto ecosystem
- Token-specific name mentions (cross-source validation for OG resolution)
- Narrative lifecycle tracking within crypto context

---

## Source Category: Social Platforms (Public)

**What it provides:**
- Public posts mentioning narrative terms or token names
- Engagement metrics (likes, reposts, replies) as proxy for attention
- Velocity of social discussion over time
- Influencer mentions

**Trust profile:**
- Easily gamed — Tier 1
- Every social metric should be treated as potentially fabricated
- Corroboration across multiple independent accounts and source types required

**Freshness:**
- Real-time or near-real-time depending on API access

**Limitations:**
- Streaming access to major platforms is expensive or restricted
- Bot detection is imperfect — many "human" accounts are automated
- Platform API policies change frequently; access may be disrupted

**Critical signals this source enables:**
- Early narrative detection (social often precedes news)
- Social attention measurement for narrative strength scoring
- Cross-source validation for OG token mentions

**Special handling:** Social data is never used as the sole basis for any score above `watch` tier. It must be corroborated by at least one other source category.

### X (Twitter) — Implemented

X is a first-class, real-time narrative signal layer. See `docs/ingestion/x-twitter-integration.md` for full design.

- **Adapter:** `XAPIAdapter` in `src/mctrend/ingestion/adapters/x_api.py`
- **Mode:** Polling via X API v2 Recent Search (`/tweets/search/recent`)
- **Source type:** `social_media`
- **Source name:** `@<author_handle>` (per-tweet attribution)
- **Signal extraction:** Deterministic (no LLM) — cashtag extraction, hashtag extraction, engagement scoring, bot/spam filtering
- **Rate limiting:** Credit-based budget with exponential-backoff cooldown, state persisted across restarts
- **Degraded mode:** Pipeline continues without X; `x_source_available: false` in cycle summary

---

## Source Category: Community Channels

**What it provides:**
- Token-specific Telegram groups, Discord servers, community chats
- Volume and activity of community discussion
- Insider information (but cannot be distinguished from manipulation)

**Trust profile:**
- Very high manipulation risk — Tier 1 (highest suspicion)
- All activity in a token's own community channel should be assumed to be deployer-controlled or deployer-influenced
- Community channel signals should not increase positive scores; they can only contribute to risk flags (e.g., suspicious coordinated activity)

**Freshness:**
- Real-time

**Limitations:**
- Accessing private community channels requires presence in them — not scalable
- Monitoring these at scale requires significant infrastructure
- Signal-to-noise ratio is extremely low

**Current system position:** Community channel monitoring is **out of scope for initial implementation**. If implemented, signals from these sources must be heavily discounted and treated as Tier 1.

---

## Source Category: Cross-Reference Lists

**What it provides:**
- Lists of known bad-actor deployer wallets
- Lists of known rug contract patterns
- Flagged addresses from community intelligence networks

**Trust profile:**
- Quality depends entirely on list source — Tier 2 to Tier 3 if from reliable source
- Community-submitted lists need independent validation

**Freshness:**
- Periodic updates (hours to days)

**Limitations:**
- Known bad actors create fresh wallets; lists lag behind reality
- False positives possible (legitimate address incorrectly flagged)
- No single authoritative list exists

**Critical signals this source enables:**
- Deployer risk scoring (known-bad deployer is a critical risk flag)
- Rapid early risk detection without full on-chain analysis

---

## Source Dependency Risk

The system should never be critically dependent on a single source for any core function.

| Function | Minimum Sources Required |
|---|---|
| Token discovery | 1 (chain is authoritative for this) |
| Narrative detection | 2+ source types |
| Rug risk assessment | On-chain data is primary; cross-reference is supplementary |
| Momentum analysis | On-chain required; social is supplementary |
| Attention measurement | 2+ source types preferred; 1 accepted with confidence penalty |

When a required source is unavailable, the affected dimension scores are computed with available data, and `confidence_score` is reduced proportionally.
