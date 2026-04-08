# Current Implementation Approach

This document describes the current concrete tooling and implementation choices. These choices are **explicitly subject to change** and should not be treated as permanent architecture. The stable architecture is in `docs/architecture/`.

When any implementation choice changes, update this document. The existence of this document prevents the stable architecture docs from becoming polluted with tool-specific details.

---

## Language and Runtime

**Current choice:** Python 3.11+

**Rationale:** Good ecosystem for data processing, strong library support for the required data manipulation tasks, fast iteration speed.

**Alternatives considered:** TypeScript/Node.js (good async, strong API client ecosystem). Not chosen initially due to Python's stronger data processing ecosystem.

**This choice should be revisited if:** Performance becomes a bottleneck in the ingestion or scoring pipelines.

---

## On-Chain Data Access

**Current choice:** Solana RPC endpoints (standard Solana JSON-RPC protocol) via a hosted RPC provider for reliability.

**Rationale:** Standard interface, stable API, available from multiple providers.

**What this covers:** Token account creation events, transaction history, account balance/holder data.

**Limitations:** Rate limits apply. Historical data (beyond recent blocks) may require archive node access. Real-time streaming requires websocket subscriptions, which add connection management complexity.

**Alternatives:** Self-hosted RPC node (eliminates rate limits but adds ops burden), dedicated Solana indexing APIs (faster/richer queries but adds cost and provider dependency).

---

## Token Launch Platform

**Current choice:** Pump.fun API + websocket for real-time token launch events.

**API endpoint:** Not documented here — stored in configuration. Pump.fun's API is undocumented and subject to change without notice. Monitor for breakage.

**Fragility note:** Pump.fun does not provide a public documented API. Current integration is based on observed API behavior. This is a fragile dependency. If Pump.fun changes their API, the token ingestion pipeline will break. Build monitoring for this.

**Fallback:** On-chain token creation monitoring as fallback if platform API fails.

---

## Trend / Narrative Detection Sources

**Current choices:**
- **Search trends:** SerpAPI or Google Trends (via unofficial client) for search trend data
- **News:** NewsAPI.org for English-language news aggregation
- **Crypto news:** CoinDesk RSS feed, CoinTelegraph RSS feed

**Limitations:**
- Google Trends unofficial client is fragile and may break
- NewsAPI free tier has limited request rate and 24-hour delay on some endpoints
- RSS feeds require parsing and are not always real-time

**Planned improvements:** Evaluate official search trend APIs, broader news aggregation, additional crypto media sources.

---

## Social Signal Sources

**Current choice:** X/Twitter API (Basic tier or above) for Twitter signal data.

**Limitations:**
- X API pricing and access tiers have changed significantly. Current access level limits request volume.
- Bot detection relies on X's own labels, which are imperfect.
- Rate limits constrain polling frequency.

**Status:** Social data is treated as Tier 1 (high suspicion) regardless. Its primary value is narrative velocity measurement, not signal accuracy.

**Alternative if X API access degrades:** Reddit API (for trending topics), Farcaster public feed (smaller but more reliable).

---

## Storage

**Current choice:** PostgreSQL for persistent record storage (token registry, narrative registry, alert registry, scoring history).

**Rationale:** Reliable, queryable, good JSON column support for flexible schema fields like `data_gaps[]` and `history[]`.

**Schema:** Defined in `docs/implementation/data-model.md`.

**Cache layer:** Redis for short-lived state (in-progress scoring runs, deduplication lookups, rate limiting counters).

---

## Task Queue / Pipeline Execution

**Current choice:** Celery + Redis for async task execution.

**Tasks:**
- Supplementary chain data fetch (async after token registration)
- Scoring pipeline tasks (one per token-narrative link)
- Alert delivery tasks
- Re-evaluation tasks

**Rationale:** Simple, well-understood, easy to monitor.

**Alternative:** If the system grows, consider a dedicated queue system or stream processing framework. Do not over-engineer for this initially.

---

## LLM Integration (When Used)

**Current choice:** Anthropic API (Claude) for semantic matching tasks.

**Used for:**
- Narrative-to-token name semantic matching (Layer 4 in `docs/intelligence/narrative-linking.md`)
- Not used for scoring decisions
- Not used for rug risk assessment

**Constraints on LLM usage:**
- Always validate LLM output against structured constraints
- Always log LLM inputs and outputs
- Never use LLM output as a single source of truth above `verify` tier
- See `docs/implementation/agent-strategy.md` for full LLM usage policy

**Model:** Currently configured to use a mid-tier model for cost efficiency. Task does not require the most capable model.

---

## Delivery Channels

**Current choices:**
- Telegram Bot API for push notifications
- Webhook delivery for integration consumers
- PostgreSQL (alert registry) as persistent log

**Telegram specifics:** Uses the bot API. Bot token stored in configuration. Rate limits: 30 messages/second. Per-chat rate limits apply separately.

---

## Scheduling

**Current choice:** Celery Beat for scheduled tasks (polling, expiry checks, re-evaluation runs).

**Scheduled tasks:**
- Event ingestion: every 5 minutes (news/social), every 20 minutes (search trends)
- Alert expiry check: every 10 minutes
- Re-evaluation runs: every 30 minutes for DECLINING narratives, every 2 hours for PEAKING

---

## Configuration Management

All API keys, rate limits, threshold values, and weight parameters are stored in configuration — not hardcoded.

**Current approach:** Environment variables for secrets (API keys), `.env` file for local development, configuration YAML for non-secret operational parameters.

**Configurable parameters include:**
- All dimension weights (from `docs/intelligence/probability-framework.md`)
- All alert classification thresholds (from `docs/alerting/alert-types.md`)
- All rate limits and polling intervals
- Minimum qualification thresholds for token ingestion

**Change process:** To change a configurable parameter, update the configuration and update the relevant doc that defines the parameter's meaning. Never change a threshold without updating the doc.

---

## Monitoring and Observability

**Current minimal setup:**
- Structured JSON logging to stdout (collected by whatever log aggregation is in use)
- Alert registry serves as audit trail for alert decisions
- Source gap logs track data availability

**Not yet implemented:**
- Metrics/dashboards (Prometheus, Grafana, or equivalent)
- Alerting on system health (source downtime, error rate spikes)
- Calibration tracking dashboard

These are high-priority items for the second operational phase.

---

## Known Fragility Points

These are implementation choices that are known to be fragile and should be improved:

1. **Pump.fun API** — Unofficial, undocumented, will break. Build fallback.
2. **Google Trends** — Unofficial client, rate-limited, unclear terms of service. Consider replacing.
3. **Twitter/X API** — Access tier constraints limit polling frequency. Monitor.
4. **LLM API latency** — Semantic matching via LLM adds latency to the correlation pipeline. If latency is a problem, precompute or cache more aggressively.
5. **Redis as single-point cache** — No replication in initial setup. Acceptable for MVP; improve for production.
