# Source Catalog

This document catalogs known data sources, what they provide, their reliability profile, access requirements, and known limitations. This is a living document — add new sources as they are evaluated.

---

## On-Chain / Token Data

### Solana RPC (Standard JSON-RPC)

**Category:** On-chain  
**Provides:** Token accounts, transaction history, account balances, program interactions  
**Trust tier:** 2 (accurate but interpretable adversarially)  
**Reliability:** High if using a quality hosted provider; self-hosted requires maintenance  
**Latency:** Seconds  
**Access:** Requires RPC endpoint (hosted or self-hosted). Public endpoints are rate-limited and unreliable for production use.  
**Rate limits:** Varies by provider; dedicated nodes have no rate limits  
**Known issues:**
- Public endpoints are heavily rate-limited
- Historical queries (archive node) are expensive
- Program account parsing requires understanding each program's schema

---

### Pump.fun Platform API

**Category:** Token launch platform  
**Provides:** New token launches, early trading metrics, token metadata, bonding curve state  
**Trust tier:** 2 for on-chain data, 1 for metadata (deployer-controlled)  
**Reliability:** Medium — undocumented API, subject to unannounced changes  
**Latency:** Seconds (websocket), ~10 seconds (polling)  
**Access:** No official API documentation. Current integration based on observed behavior.  
**Rate limits:** Unknown / not officially documented  
**Known issues:**
- No SLA or official support
- API has changed without notice historically
- Graduation event (bonding curve completion) sometimes has delayed reflection in API
- Metadata is entirely deployer-controlled (untrusted)

**Monitoring requirement:** Build health checks that verify the API is returning plausible data. Alert operator if the format changes.

---

### Birdeye / DexScreener / similar aggregators

**Category:** On-chain aggregated data  
**Provides:** Token price, volume, holder data, trade history in pre-aggregated form  
**Trust tier:** 2  
**Reliability:** Medium-High; commercial services with better uptime than DIY chain queries  
**Latency:** 1–5 minutes for aggregated metrics  
**Access:** API keys required; pricing varies  
**Known issues:**
- May not have data for brand new tokens (takes time to index)
- Aggregated metrics can lag 1–5 minutes behind actual chain state
- Different aggregators may disagree on holder counts (depends on how they count DEX addresses)

**Use case in this system:** Supplementary source for price/volume data. Primary on-chain source is still direct RPC for critical rug risk fields.

---

## Trend / Narrative Sources

### Google Trends

**Category:** Search trends  
**Provides:** Relative search volume for terms, trending topics, geographic distribution  
**Trust tier:** 2 (hard to fake at scale)  
**Reliability:** High (Google infrastructure), but data has inherent ~4-6 hour lag in some modes  
**Latency:** 15–60 minutes depending on API mode used  
**Access:** Official API requires Google Cloud project. Unofficial clients exist but are against terms of service.  
**Rate limits:** Official API has quota limits. Unofficial clients get rate-limited aggressively.  
**Known issues:**
- Relative scale (0–100) not absolute numbers; makes cross-time comparison unreliable
- Geo-filtering affects results — US trends ≠ global trends
- Very fast micro-trends (< 30 minutes) may not appear in available data

---

### NewsAPI.org

**Category:** Mainstream news  
**Provides:** Published articles from hundreds of news outlets, headline + description + URL  
**Trust tier:** 2  
**Reliability:** High; commercial service  
**Latency:** 5–15 minutes for most articles  
**Access:** API key required; free tier has significant limitations (24h delay for some sources, limited requests)  
**Rate limits:** Depends on plan; free tier is very limited  
**Known issues:**
- Article content requires separate fetch (body not included in API response)
- Some outlets not covered
- NLP entity extraction must be done by us (API provides raw text, not entities)

---

### CoinDesk / CoinTelegraph / The Block (RSS)

**Category:** Crypto-native news  
**Provides:** Crypto-specific news articles, market coverage, project announcements  
**Trust tier:** 1–2 (content quality varies; some sponsored content mixed with editorial)  
**Reliability:** Medium; RSS feeds are generally stable  
**Latency:** 5–15 minutes  
**Access:** Public RSS feeds — no authentication required  
**Rate limits:** None for RSS  
**Known issues:**
- RSS feeds don't always include full article text
- Crypto media has significant promotional bias
- Sponsored/paid articles not always clearly labeled
- Used primarily for early narrative detection within crypto context

---

## Social Platforms

### X / Twitter API

**Category:** Social  
**Provides:** Tweets, trending topics, account metrics, hashtag data  
**Trust tier:** 1 (easily gamed; bot-heavy)  
**Reliability:** Medium; API access and pricing have changed significantly  
**Latency:** Real-time (streaming) or minutes (REST polling)  
**Access:** Requires developer account; tier determines rate limits and access features  
**Rate limits:** Significant and tiered; basic tier is very constrained  
**Known issues:**
- Bot detection is imperfect and largely relies on X's own labels
- Streaming access requires elevated tier
- API changes have broken integrations without notice
- Rate limits may prevent adequate polling during high-volume news cycles

**Current status:** Usable at basic tier for polling trending hashtags and mentions. Streaming access would significantly improve signal quality.

---

### Reddit API

**Category:** Social  
**Provides:** Posts and comments from crypto-relevant subreddits (r/SolanaMemeCoins, r/CryptoMoonShots, etc.)  
**Trust tier:** 1 (gamed but less saturated with bots than Twitter)  
**Reliability:** Medium; Reddit API access terms and pricing changed significantly in 2023  
**Latency:** Minutes  
**Access:** API key required  
**Rate limits:** 100 requests/minute (OAuth)  
**Known issues:**
- Community-specific; doesn't reflect broader cultural attention
- Upvote/downvote manipulation is possible
- Subreddit coverage is niche; may miss narratives that spread on other platforms

**Use case:** Secondary corroboration. Cross-referencing Reddit mentions with Twitter trends adds source diversity value.

---

## Cross-Reference / Risk Lists

### Rug Pull Lists (Community-Maintained)

**Category:** Risk cross-reference  
**Provides:** Lists of known rug pull contract addresses and deployer wallets  
**Trust tier:** 2–3 depending on list curation quality  
**Reliability:** Variable; community-maintained lists may have gaps or false positives  
**Latency:** Hours to days (not real-time)  
**Access:** Various; some are public GitHub repos, some are API-based  
**Known issues:**
- Lists lag behind new rugs
- False positives possible (legitimate address incorrectly flagged)
- No single authoritative list exists
- Coverage varies by chain and time period

**Best practice:** Use multiple lists. Weight by source reliability. Treat as a one-way signal: being on a bad actor list is strong risk signal; not being on a list is not a safety signal.

---

## Sources Evaluated and Rejected

### On-chain mempool data

**Evaluated:** Could provide earliest possible signal on pending token launches  
**Rejected reason:** Complexity is too high for value at this stage. Mempool data is messy, ephemeral, and requires specialized tooling. Chain event data post-confirmation is sufficient for current purposes.

### Telegram monitoring (token community channels)

**Evaluated:** High signal about community activity  
**Rejected reason:** Accessing Telegram communities at scale requires being a member, has privacy implications, and produces extremely noisy data that is almost entirely deployer-influenced. Signal-to-noise too low for current scope.

---

## Adding New Sources

When adding a new source to the system:
1. Add an entry to this document with all fields filled in
2. Assign a trust tier and document the rationale
3. Identify what specific system function this source serves (narrative detection, rug risk, etc.)
4. Note any legal or terms-of-service constraints on using the data
5. Build monitoring for source availability from day one
