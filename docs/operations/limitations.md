# System Limitations

This document states what the system does not do, what data is missing, and what operators should not rely on.

---

## Data Limitations

### Chain enrichment is partial

The Solana RPC adapter (`fetch_token_holders`) returns the top 20 accounts with raw token amounts. Percentage calculations (e.g., `top_5_holder_pct`) require total supply, which is fetched separately via `fetch_token_data`. These amounts are not yet automatically joined into chain snapshots during ingestion — the pipeline currently stores whatever data is available and applies conservative defaults for missing fields.

**Impact:** Rug risk scores for tokens with missing concentration data will use conservative defaults, resulting in lower scores than a fully-enriched token would receive.

### Wallet clustering is not implemented

The rug risk scoring dimension includes a wallet clustering signal, but the adapter layer does not currently perform graph-based clustering analysis. All tokens receive a conservative default for this dimension.

**Impact:** Organized rug pulls using closely related wallets will not be flagged by clustering signals.

### Social data is not collected

The social scoring dimension (`social_data`) is always empty (`{}`). Twitter/X, Discord, and Telegram group data are not ingested. Social scores default to conservative.

**Impact:** Momentum signals from social channels are not available. Tokens with genuine viral social momentum may score lower than reality.

### Deployer history lookup is not implemented

The `deployer_known_bad` and `deployer_prior_deployments` fields are not populated by any live adapter. They must be set manually via chain snapshot injection or remain at their defaults (false, None).

---

## Operational Limitations

### Single-process, single-node only

The system uses SQLite with WAL mode. Multiple simultaneous writer processes will cause lock contention. Do not run more than one instance against the same database file.

### No cross-restart dedup for high-volume

In-memory delivery deduplication covers the current session. The system loads delivery history at startup for recently delivered alerts, but in high-volume scenarios, very old alerts may be re-delivered after a restart if they fall outside the delivery log's retention window. This is an edge case in normal operation.

### Rate-limited alerts are not re-queued

When the delivery rate limit is exceeded, the alert is logged as `rate_limited` in `alert_deliveries` and is not automatically retried in the next cycle. High-burst scenarios (many tokens matching a single narrative simultaneously) may result in some alerts not being pushed to Telegram or webhooks.

### No alert replay

There is no mechanism to re-deliver historical alerts to a new delivery channel. Adding Telegram after the system has been running will not send a backfill of existing active alerts.

---

## Scoring Limitations

### Conservative defaults favor false negatives

When data is missing (chain snapshot not available, no social data), the system applies conservative defaults as required by `docs/rules/engineering-rules.md`. This means tokens with genuinely low rug risk may score higher than warranted due to missing concentration data, and tokens with genuine momentum may be classified as `watch` instead of `possible_entry`.

This is intentional. The system is calibrated to produce false negatives rather than false positives.

### Probability outputs are not calibrated probabilities

The `net_potential`, `p_potential`, and `p_failure` values are scored indices, not statistically calibrated probabilities. They should be interpreted as relative ranking signals, not as literal probabilities of success or failure.

---

## What This System Is Not

- Not a trading bot — it does not place trades or manage positions
- Not a financial advisor — its outputs are not financial advice
- Not a price predictor — it does not forecast price movements
- Not a safety guarantor — high scores do not indicate "safe to trade"
- Not a certainty engine — no alert implies certainty of any outcome

See `docs/core/03-scope-and-non-goals.md` for the full scope definition.
