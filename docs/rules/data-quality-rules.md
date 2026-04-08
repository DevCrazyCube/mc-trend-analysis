# Data Quality Rules

These rules define minimum data quality requirements at each stage of the pipeline. They specify what must be true about data before it proceeds, and how to handle data that fails quality checks.

---

## Rule 1: Required vs. Optional Fields

Every normalized record has fields classified as `required` or `optional`.

**Required fields** must be non-null for the record to be valid. A record with null required fields is rejected at normalization, not passed downstream.

**Optional fields** may be null. Null optional fields are logged in `data_gaps[]` and reduce `confidence_score` in downstream scoring.

### Required fields by record type:

**TokenRecord:**
- `address` — without this, the token cannot be identified
- `name` — primary input for narrative matching
- `deployed_by` — primary input for deployer risk
- `launch_time` — required for timing quality calculation
- `launch_platform` — required for context

**EventRecord:**
- `anchor_terms` — must have at least one term; without terms, no correlation is possible
- `attention_score` — required for narrative scoring
- `state` — required for timing quality
- `first_detected` — required for lifecycle tracking

**ChainDataRecord:**
- `token_id` — must be linked to a token
- `sampled_at` — required for freshness calculation

**ScoredToken:**
- `link_id` — must be linked to a TokenNarrativeLink
- `scored_at` — required for freshness
- `net_potential` — may not be null; if data prevents computation, use conservative default and flag

---

## Rule 2: Data Freshness Requirements

Data older than defined thresholds must be flagged as stale before use in scoring.

| Data Type | Freshness Threshold | Action if Stale |
|---|---|---|
| ChainDataRecord (for scoring) | 30 minutes | Flag `data_freshness: stale`, reduce confidence |
| NarrativeSource signal | 60 minutes | Reduce attention score contribution, flag |
| SocialRecord | 30 minutes | Flag stale, reduce confidence |
| TokenChainSnapshot (for alerts) | 15 minutes | Trigger re-fetch before alert generation |
| Alert (for display) | 2 hours (type-specific expiry) | Trigger re-evaluation |

Stale data is not rejected — it is used with reduced confidence and explicitly flagged. The user-facing alert must show `DATA_GAP` or `STALE_DATA` flags when applicable.

---

## Rule 3: Data Completeness Minimums

The scoring pipeline requires minimum data completeness to proceed.

**Minimum completeness to score (compute probabilities):** 4 of 6 dimensions must have non-null inputs. If fewer than 4 dimensions can be scored, produce a `verify`-tier alert maximum with `LOW_CONFIDENCE` flag and `confidence_score ≤ 0.40`.

**Minimum completeness for `possible-entry`:** All 6 dimensions must have non-null inputs. No exceptions. The `possible-entry` tier requires complete evidence.

**Minimum completeness for rug risk assessment:** At least deployer + concentration data (categories 1 and 2) must be available. If neither is available, the token cannot receive any alert above `watch` tier.

---

## Rule 4: Source Gap Handling

When a source is unavailable (network error, rate limit, API change), the system must:

1. Log a `SourceGap` record with start time, source name, and source type
2. Continue processing tokens with available data
3. Reduce `confidence_score` proportionally to the missing source's contribution
4. Add the source name to `data_gaps[]` on affected records
5. Update the `SourceGap` record with end time when the source becomes available again

Do not halt the pipeline because one source is unavailable. The system must degrade gracefully.

---

## Rule 5: Anomalous Data Must Be Flagged, Not Rejected

When data values are outside expected ranges but structurally valid, flag them — do not silently reject them.

Examples of anomalous-but-valid data:
- Holder count that drops by 80% in 10 minutes (possible dump, possible data error)
- Volume that is 1000x average in a single 5-minute window (possible wash trade, possible viral event)
- Narrative attention score at maximum (100/100) across all sources simultaneously (possible data error, possible major event)

**Handling:**
- Accept the data
- Flag with an `ANOMALOUS_DATA` marker on the record
- Log the anomaly with enough context to investigate
- Apply additional uncertainty discount to any dimension score derived from anomalous data

---

## Rule 6: Deduplication Must Be Exhaustive

Before creating any new record, check for duplicates:
- TokenRecord: check by `address` (Solana address)
- EventRecord: check by anchor term overlap within time window
- Alert: check by `token_id` + active status (only one active alert per token at a time)
- AlertDelivery: check by `alert_id` + `channel_id` (do not re-deliver the same alert state to the same channel)

Deduplication failures (creating duplicates) are treated as data quality bugs, not operational issues. They corrupt the dataset.

---

## Rule 7: Timestamp Consistency

All timestamps stored in the system must be UTC. No timezone offsets stored. All timestamps are ISO 8601 format.

When a source provides timestamps in a non-UTC timezone or non-standard format:
- Convert to UTC during normalization
- Log the original format for auditability
- If timezone cannot be determined, flag `data_gaps: ["timestamp_timezone_unknown"]` and assume UTC with explicit uncertainty

---

## Rule 8: Chain Data Must Match Token Identity

When fetching chain data for a token, verify that the chain data returned corresponds to the correct contract address. API responses that return data for a different address (due to pagination errors, caching, etc.) must be rejected.

Verification: `ChainDataRecord.address` must match `Token.address`. If they don't match, reject the chain data and log a data consistency error.

---

## Rule 9: Social Signal Quality Floor

Social records with estimated bot percentage > 70% are discounted to zero contribution for attention scoring purposes. They are retained in the record for audit but excluded from scoring.

Social records with estimated bot percentage 50–70% have their signal strength multiplied by `(1 - estimated_bot_pct)`.

If bot percentage cannot be estimated, apply a default discount of 0.30 (assume 30% bot traffic as a conservative floor for social signals).

---

## Rule 10: Historical Scoring Data Is Ground Truth

Once a ScoredToken record is written, its values are permanent. Reprocessing a token to improve scores produces a new ScoredToken record, not an update to the existing one.

The original record's values — even if they were computed with incomplete data or stale signals — are the historical ground truth for calibration purposes. Retroactively changing them to make the model "look better" is explicitly prohibited.
