# Normalization

This document defines the canonical record schemas and how heterogeneous source data is normalized to common formats.

---

## Why Normalization Matters

Each data source has its own format, naming conventions, data types, and quirks. The normalization layer creates a clean separation between the chaos of external APIs and the clean assumptions the rest of the system can make.

Without normalization:
- Scoring code must handle source-specific formats
- Adding a new source requires changes deep in the business logic
- Missing fields from one source cause bugs in code written for another

With normalization:
- All code downstream of the normalization layer works with predictable, typed records
- New sources require only a new normalizer adapter
- Missing fields are handled uniformly via explicit null/unknown states

---

## Canonical Record Types

The system defines four canonical record types:

### 1. TokenRecord

Already defined in `docs/ingestion/token-ingestion.md`. Summary of key fields:

```
TokenRecord:
  token_id: uuid
  address: solana_address
  name: string
  symbol: string
  description: string | null
  deployed_by: solana_address
  launch_time: timestamp
  launch_platform: string
  initial_liquidity_usd: float | null
  initial_holder_count: int | null
  mint_authority_status: "active" | "renounced" | "unknown"
  freeze_authority_status: "active" | "renounced" | "unknown"
  status: enum
  data_gaps: [string]
  data_sources: [string]
```

---

### 2. EventRecord

Already defined in `docs/ingestion/event-ingestion.md`. Summary:

```
EventRecord:
  narrative_id: uuid
  anchor_terms: [string]
  related_terms: [string]
  entities: [EntityRef]
  attention_score: float
  narrative_velocity: float
  state: "EMERGING" | "PEAKING" | "DECLINING" | "DEAD"
  sources: [SourceRef]
  first_detected: timestamp
  updated_at: timestamp
  data_gaps: [string]
```

---

### 3. ChainDataRecord

Contains on-chain state for a specific token at a specific point in time.

```
ChainDataRecord:
  token_id: uuid
  address: solana_address
  sampled_at: timestamp

  // Holder data
  holder_count: int | null
  top_5_holder_pct: float | null  // % of supply held by top 5 non-pool wallets
  top_10_holder_pct: float | null
  new_wallet_holder_pct: float | null  // % of holders with wallets < 24h old

  // Liquidity data
  liquidity_usd: float | null
  liquidity_locked: bool | null
  liquidity_lock_duration_hours: int | null  // null if not locked
  liquidity_providers: int | null  // number of distinct liquidity providers

  // Volume/activity
  volume_1h_usd: float | null
  volume_24h_usd: float | null
  trade_count_1h: int | null
  unique_traders_1h: int | null

  // Deployer state
  deployer_address: solana_address
  deployer_tx_count: int | null
  deployer_known_bad: bool  // from cross-reference list
  deployer_prior_deployments: int | null

  // Data quality
  data_gaps: [string]
  data_source: string
```

---

### 4. SocialRecord

Contains social signal data for a specific narrative or token at a point in time.

```
SocialRecord:
  record_id: uuid
  source_type: "twitter" | "reddit" | "telegram" | "discord" | "other"
  source_name: string
  sampled_at: timestamp

  // Subject
  subject_type: "narrative" | "token"
  subject_id: uuid  // narrative_id or token_id

  // Signal strength
  mention_count: int | null  // how many times subject was mentioned in this sample
  engagement_score: float | null  // normalized engagement (likes, reposts, etc.)
  unique_account_count: int | null  // distinct accounts mentioning subject

  // Quality signals
  estimated_bot_pct: float | null  // estimated percentage of bot accounts
  verified_account_mentions: int | null  // mentions from verified/notable accounts

  // Context
  sentiment: float | null  // -1.0 to 1.0 (if computed); null if not computed
  trending_rank: int | null  // rank on platform's trending list if available

  // Data quality
  data_gaps: [string]
  reliability_tier: 1 | 2 | 3
```

---

## Normalization Rules

### Rule 1: Explicit Nulls, No Defaults

If a field cannot be populated from the source data, it must be set to `null` and the field name added to `data_gaps[]`. Never infer a value or use a default value in the normalized record.

Defaults (like "assume 0 for unknown volume") are applied in the scoring layer, where defaults are explicit and documented. The normalized record is the raw truth: available or not available.

---

### Rule 2: Source Timestamps

Every record must carry two timestamps:
- `sampled_at` or `published_at`: when the data was generated/published by the source
- System ingestion timestamp: when the system received and normalized it

Both are required. If the source does not provide its own timestamp, use the ingestion timestamp and flag `data_gaps: ["source_timestamp_missing"]`.

---

### Rule 3: Float Precision

All float values are stored and transmitted with sufficient precision (at least 4 decimal places). Rounding for display happens in the presentation layer, not during normalization or scoring.

---

### Rule 4: Boolean Unknowns

Some boolean fields (e.g., `liquidity_locked`) may be unknown rather than true/false. These fields use a three-state type: `true | false | null`. `null` means "unknown," not "false." Downstream code must handle all three states explicitly.

---

### Rule 5: Address Normalization

Solana addresses are stored in base58 encoding. All address fields are normalized to lowercase base58. Addresses with checksum variants are normalized to their canonical form.

---

### Rule 6: Source Attribution

Every normalized record must carry a reference to its source(s) in `data_sources[]`. This enables:
- Debugging: "where did this value come from?"
- Trust scoring: different sources have different reliability tiers
- Audit: full traceability from output to input

---

## Normalization Validation

After normalization, the normalizer runs a validation pass:

**Required field check:** Fields marked as required must not be null. If required fields are missing, the record is rejected (logged as a normalization failure, not silently dropped).

**Type check:** All fields must be their declared types. Mismatched types (e.g., string where float expected) are rejected.

**Range check:** Values must fall within expected ranges (e.g., percentages between 0 and 1, holder counts must be non-negative).

**Consistency check:** Some fields have logical relationships (e.g., `top_10_holder_pct` should be ≥ `top_5_holder_pct`). Violations are logged as data quality warnings, not rejections.

---

## Normalization Errors and Recovery

When a normalizer fails to parse or normalize a raw record:

1. Log the failure with the raw record content (truncated if very large)
2. Log the specific error (field, type mismatch, missing required field, etc.)
3. Increment the error counter for this source
4. Do not produce a partial record — either the record normalizes completely or it doesn't

If error rate for a source exceeds a threshold (configurable; default: 10% of records in last 100), raise an alert to the operator that the source adapter may need updating.

---

## Schema Versioning

Normalized record schemas are versioned. Each record carries a `schema_version` field.

When a schema changes:
- Increment the version number
- Update this document
- Maintain backward-reading code for N-1 versions during transition

Do not silently change the schema without versioning it. Downstream systems rely on schema stability.
