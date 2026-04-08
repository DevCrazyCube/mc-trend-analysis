# Token Ingestion

This document defines how new token candidates enter the system and pass initial qualification.

---

## Token Discovery Trigger

Tokens enter the system when a new token creation event is detected on Pump.fun or a compatible Solana token launchpad.

**Detection methods (in priority order):**
1. **Websocket event feed** — real-time stream of new token creation events from the platform
2. **Polling the token launch endpoint** — periodic polling if websocket is unavailable
3. **On-chain event monitoring** — detect new token program account creation directly on Solana

The system does not discover tokens by searching social media. Tokens enter through authoritative on-chain or platform sources first.

---

## Initial Qualification

Not every new token warrants full processing. An initial qualification pass filters out tokens that clearly cannot match any active narrative.

**Minimum qualification criteria:**

| Criterion | Requirement | Notes |
|---|---|---|
| Token address | Must be a valid Solana address | Reject malformed addresses |
| Launch time | Must be within last 4 hours | Ignore tokens we discover late |
| Name/symbol | Must be non-empty and non-garbage | Reject pure numeric or random-character names |
| Initial liquidity | Must be > minimum threshold | Configurable, e.g., > $500 USD equivalent |
| Token program | Must match expected program IDs | Reject tokens from unknown programs |

Tokens that fail any qualification criterion are logged and discarded without further processing.

---

## Token Record Schema

Every qualified token produces a `TokenRecord`:

```
TokenRecord {
  // Identity
  token_id: string (internal UUID),
  chain: "solana",
  address: string (Solana address),
  name: string,
  symbol: string,
  description: string | null,
  image_uri: string | null,

  // Launch data
  deployed_by: string (deployer wallet address),
  launch_time: timestamp,
  launch_platform: string (e.g., "pump.fun"),
  first_seen_by_system: timestamp,

  // Initial chain state (at time of discovery)
  initial_liquidity_usd: float | null,
  initial_holder_count: int | null,
  initial_supply: int | null,

  // Contract characteristics
  mint_authority_status: "active" | "renounced" | "unknown",
  freeze_authority_status: "active" | "renounced" | "unknown",

  // Status tracking
  status: "new" | "linked" | "scored" | "alerted" | "expired" | "discarded",
  linked_narratives: [narrative_id],
  created_at: timestamp,
  updated_at: timestamp,

  // Data quality
  data_gaps: [string],  // fields that could not be populated
  data_sources: [string]  // which sources provided this data
}
```

**Key design note:** Deployer-controlled fields (name, description, image_uri) are clearly separated from on-chain verified fields. They are used for narrative matching but carry no trust weight in risk scoring.

---

## Supplementary Chain Data Fetch

After initial registration, the system fetches additional on-chain data:

1. **Deployer history** — transaction history of the deployer wallet, cross-referenced against known bad-actor lists
2. **Holder distribution** — top wallet holdings as percentage of supply (excluding known DEX/pool addresses)
3. **Liquidity details** — liquidity pool structure, lock status, provider composition
4. **Contract analysis** — verify mint authority, freeze authority, and contract program type

This supplementary fetch happens asynchronously after token registration. The token enters the correlation pipeline before supplementary data is available; when it arrives, the scoring pipeline runs (or re-runs) with the complete data.

---

## Deduplication

The same token may be seen from multiple sources (platform API + on-chain event + social mention). Deduplication uses the contract address as the primary key.

**Deduplication rules:**
- If a token with the same `address` already exists in the registry: update the existing record with any new data fields, do not create a second record
- If a token is seen from a new source: add the source to `data_sources[]` list
- If conflicting data is received from two sources: prefer on-chain data over platform data over social data; log the conflict

---

## Token Status Lifecycle

```
new → linked → scored → alerted
                              │
                        re-evaluated
                              │
              ┌───────────────┼───────────────┐
           alerted       score changed      retired
          (continued)         │               │
                         (update alert)   (discard/expire)
```

**Status definitions:**

| Status | Meaning |
|---|---|
| `new` | Token registered, awaiting correlation |
| `linked` | Correlated to one or more narratives, awaiting scoring |
| `scored` | Scoring complete, awaiting or in alert classification |
| `alerted` | One or more active alerts exist for this token |
| `expired` | No active alerts, monitoring window elapsed |
| `discarded` | Token ruled out (rug confirmed, narrative dead, criteria failed) |

---

## Handling Pump.fun Graduation Events

When a Pump.fun token "graduates" (completes the bonding curve and migrates to a standard AMM), this is a significant lifecycle event:

- Liquidity structure changes (from bonding curve to AMM pool)
- Trading dynamics change (price discovery moves to open market)
- Re-run liquidity risk assessment with new liquidity data
- Trigger re-evaluation of active alerts

Graduation is a neutral signal — it means the token achieved significant early traction, but it does not reduce rug risk or improve opportunity estimates on its own.

---

## Token Ingestion Rate Expectations

Pump.fun launches thousands of tokens per day. The ingestion pipeline must handle:
- Burst periods of hundreds of tokens per hour during viral narrative moments
- All tokens passing through initial qualification quickly (< 30 seconds)
- Supplementary data fetches without blocking the main qualification flow

**Design implication:** Supplementary chain data fetches must be asynchronous and non-blocking. Token qualification happens on initial event data. Supplementary data enriches scoring but does not gate registration.

---

## Token Ingestion Limitations

**We do not discover all tokens.** Some tokens may be launched through methods not covered by our ingestion sources (e.g., direct contract deployment not surfaced by Pump.fun's API). This is acceptable — the system optimizes for the tokens that are visible in the sources we monitor.

**Token metadata is untrusted.** The name and description provided by the deployer are the primary inputs for narrative matching but are treated as unverified. A token named "DEEPMIND" is not confirmed to be related to DeepMind — that is what the correlation engine evaluates.

**Late discovery is penalized.** Tokens discovered more than 2 hours after launch receive a timing quality penalty. Tokens discovered more than 4 hours after launch may be skipped entirely depending on configuration.
