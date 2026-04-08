# Alert Engine

This document defines how the alert engine produces, manages, and retires alerts.

---

## Responsibilities

The alert engine is responsible for:
1. Receiving scored token records
2. Classifying them into alert types
3. Creating and updating alert records
4. Managing alert lifecycle (creation, updates, expiry, re-evaluation, retirement)
5. Triggering re-evaluation when conditions change

The alert engine does **not**:
- Fetch new data
- Re-compute scores
- Format or deliver alerts (that is the delivery layer)
- Make decisions beyond defined classification rules

---

## Alert Lifecycle States

```
          [ScoredToken arrives]
                  │
                  ▼
          CLASSIFICATION
                  │
         ┌────────┴────────┐
         │                 │
    score below         score above
     minimum            minimum
         │                 │
         ▼                 ▼
     IGNORED           ACTIVE ──────────────► UPDATING
                           │                      │
                    expiry/trigger                 │
                           │                      │
                           ▼                      │
                    RE-EVALUATING ◄───────────────┘
                           │
                  ┌────────┴────────┐
                  │                 │
            type changed         no change
                  │                 │
                  ▼                 ▼
             UPDATING          SILENT UPDATE
                  │
                  ▼
              ACTIVE (continued)
                  │
         [type becomes IGNORE or DISCARD]
                  │
                  ▼
             RETIRED
```

---

## Classification Logic

Classification uses `net_potential`, `P_failure`, and `confidence_score` to assign an alert type.

See `docs/alerting/alert-types.md` for the full taxonomy and thresholds.

**Classification is deterministic** — same inputs always produce the same alert type. There is no probabilistic randomness in the classification step itself; probability already lives in the score values.

**Conservative tie-breaking:** When a token score falls exactly on a threshold boundary, classify downward (more conservative type). Never round up.

---

## Creating an Alert

When a `ScoredToken` arrives and classification produces a type that warrants alerting (i.e., type is not `ignore`):

1. Check if an active alert exists for this token
   - If yes: proceed to Update logic
   - If no: create new alert

2. New alert creation:
   ```
   alert = {
     alert_id: <uuid>,
     token_id: <from ScoredToken>,
     narrative_id: <from ScoredToken>,
     type: <classified type>,
     net_potential: <from ScoredToken>,
     P_potential: <from ScoredToken>,
     P_failure: <from ScoredToken>,
     confidence: <from ScoredToken>,
     dimension_scores: { ... },
     risk_flags: [ ... ],
     reasoning: <generated reasoning string>,
     created_at: <now>,
     expires_at: <now + expiry_window(type)>,
     re_eval_triggers: [ ... ],
     status: ACTIVE,
     history: []
   }
   ```

3. Write to alert registry
4. Trigger delivery pipeline

---

## Updating an Alert

When a `ScoredToken` arrives for a token that already has an active alert:

1. Compare new classification to current alert type
2. If type is unchanged:
   - Update scores silently (no re-delivery)
   - Update `expires_at` if appropriate
   - Log the update in `history[]`
3. If type has upgraded (e.g., `watch` → `high-potential watch`):
   - Update alert type
   - Log transition in `history[]`
   - Trigger re-delivery
4. If type has degraded (e.g., `high-potential watch` → `watch`):
   - Update alert type
   - Log transition
   - Trigger re-delivery only if degradation is significant (configurable: e.g., skip one tier drops, alert on two-tier drops)
5. If type is now `exit-risk` or `discard`:
   - Always trigger re-delivery regardless of previous type
   - Begin retirement process

**Significant change threshold:** Configurable. Default: deliver update if type changes by ≥ 1 tier, or if `P_failure` increases by ≥ 0.20, or if `net_potential` decreases by ≥ 0.15.

---

## Expiry Logic

Every alert has an `expires_at` timestamp. Default expiry windows by type:

| Alert Type | Default Expiry |
|---|---|
| `watch` | 4 hours |
| `verify` | 2 hours |
| `high-potential watch` | 2 hours |
| `possible entry` | 1 hour |
| `take-profit watch` | 30 minutes |
| `exit-risk` | 15 minutes |
| `discard` | Immediate retirement |

When an alert expires:
1. Trigger re-evaluation: fetch fresh data, re-score, re-classify
2. If new classification is same type: extend expiry, no delivery
3. If new classification is different type: update alert, trigger delivery
4. If narrative is DEAD and no other narrative link: retire alert

---

## Re-evaluation Triggers

In addition to time-based expiry, certain events trigger immediate re-evaluation:

| Trigger | Condition | Action |
|---|---|---|
| `liquidity_drop_critical` | Liquidity drops > 30% in < 1 hour | Immediate re-evaluate, prioritize P_failure |
| `holder_dump` | Holder count drops > 20% in < 30 minutes | Immediate re-evaluate |
| `deployer_exit` | Deployer wallet activity suggesting exit | Immediate re-evaluate, elevate rug risk |
| `attention_decay_fast` | Narrative attention drops > 50% in < 2 hours | Re-evaluate within 15 minutes |
| `narrative_dead` | Narrative marked DEAD in registry | Re-evaluate all linked tokens |
| `new_og_signal` | Strong new cross-source mention for a competitor token | Re-evaluate OG resolution for this namespace |
| `wash_trade_detected` | New wash trade patterns detected | Re-evaluate momentum quality |

---

## Retirement

An alert is retired when:
- It is classified as `ignore` or `discard` on re-evaluation
- The linked narrative is DEAD and no replacement narrative links exist
- The token's on-chain activity has fallen below minimum activity threshold
- Manual retirement (operator override)

Retirement does not delete the alert. It marks `status: RETIRED` and records `retired_at` and `retirement_reason`.

Retired alerts are preserved for calibration analysis.

---

## Reasoning Generation

Every alert includes a `reasoning` field — a human-readable string that explains the classification.

**Format:**
```
[Alert Type] - [Token Name] linked to [Narrative Name]

Opportunity signal: net_potential [X], P_potential [X] driven by [top 2-3 positive dimension factors].
Risk signal: P_failure [X] due to [top 1-2 risk factors].
Confidence: [X] — [brief note on data quality/gaps].

Key risk flags: [list of active risk flags].
Window estimate: [qualitative window estimate based on timing quality and narrative state].
```

**Example:**
```
HIGH-POTENTIAL WATCH — $DEEPMIND linked to "Google DeepMind Product Launch (Oct 2024)"

Opportunity signal: net_potential 0.57, P_potential 0.83 driven by strong narrative match (0.91) 
and early timing (0.79). Narrative is in EMERGING state with positive velocity.
Risk signal: P_failure 0.31 due to holder concentration (top 5 wallets hold 62% of supply) 
and unverified deployer.
Confidence: 0.74 — social source partially unavailable, on-chain data complete.

Key risk flags: HIGH_HOLDER_CONCENTRATION, NEW_DEPLOYER.
Window estimate: Narrative emerging with 2–5 hour estimated window based on current velocity.
```

Reasoning strings are generated deterministically from structured data. They are not LLM-generated prose.

---

## Alert Engine Constraints

- Alert engine is stateless between calls except through the alert registry. It does not maintain in-memory state.
- Alert engine never rejects a scored token silently. Every scored token that enters the alert engine either creates/updates an alert or is logged as below-threshold.
- Alert engine does not apply delivery-layer filtering (rate limits, user preferences). These are downstream concerns.
