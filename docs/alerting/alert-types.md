# Alert Types

This document defines the full taxonomy of alert types, their classification criteria, and required fields.

---

## Alert Type Taxonomy

The system produces eight distinct alert types, ordered from most to least opportunity signal:

| Type | Tier | Description |
|---|---|---|
| `possible-entry` | 1 (Highest opportunity) | Strong multi-dimensional signal, low failure risk |
| `high-potential-watch` | 2 | Strong opportunity signal, notable risk present |
| `take-profit-watch` | 2 | Active alert with sustained momentum, opportunity may be maturing |
| `verify` | 3 | Meaningful signal but insufficient evidence — requires human review |
| `watch` | 3 | Low-level signal worth monitoring |
| `exit-risk` | 4 (Risk alert) | Active token showing failure signals — warning |
| `discard` | 5 (Negative) | Strong failure signals, opportunity effectively eliminated |
| `ignore` | 6 (No output) | Below all thresholds — no alert generated |

---

## Classification Thresholds

### `possible-entry`

**Criteria:**
- `net_potential` ≥ 0.60
- `P_failure` < 0.30
- `confidence_score` ≥ 0.65
- Narrative state: EMERGING or PEAKING (not DECLINING)
- No critical risk flags present

**Meaning:** The best convergence of positive signals this system can identify. Multiple strong dimensions agree. Failure risk is low by observed signals. This is still not a guarantee.

**Required fields:** All fields must be populated. No missing dimension data allowed for this type.

**Expiry:** 1 hour (narrative windows this strong decay fast)

---

### `high-potential-watch`

**Criteria:**
- `net_potential` ≥ 0.45
- `P_failure` < 0.50
- `confidence_score` ≥ 0.55
- Narrative state: EMERGING or PEAKING
- May have medium risk flags but not critical

**Meaning:** Strong opportunity signal with notable risk present. Worth close attention and further verification before acting.

**Note:** Most valuable alerts will fall here or in `possible-entry`. This is the workhorse category.

**Expiry:** 2 hours

---

### `take-profit-watch`

**Criteria:**
- Token previously had `possible-entry` or `high-potential-watch` alert
- `net_potential` still ≥ 0.35
- Narrative state: PEAKING or early DECLINING
- Timing quality has decreased since initial alert (lifecycle progressing)

**Meaning:** The opportunity that was identified is maturing. The window may be narrowing. Relevant for someone who acted on an earlier alert.

**Note:** This type is only applied to tokens with prior active high-tier alerts. New tokens cannot start as `take-profit-watch`.

**Expiry:** 30 minutes

---

### `verify`

**Criteria:**
- `net_potential` ≥ 0.35
- `confidence_score` < 0.55 (insufficient evidence quality)
- OR narrative match confidence < 0.50 (ambiguous link)
- OR multiple competing narratives with close scores

**Meaning:** Something here might be significant but the evidence is incomplete or ambiguous. Requires human verification before the signal is trusted. Do not act on `verify` alerts without additional research.

**Common causes:**
- Missing social source data (so momentum can't be validated)
- Ambiguous OG resolution (namespace collision)
- New narrative with only one source so far

**Expiry:** 2 hours

---

### `watch`

**Criteria:**
- `net_potential` ≥ 0.25
- Does not meet criteria for any higher tier

**Meaning:** Low-level signal. Token has some interesting characteristics but not enough convergence to warrant active attention. Monitoring only.

**Note:** Watch alerts are low-noise background signals. They should not generate push notifications by default — see `docs/alerting/notification-strategy.md`.

**Expiry:** 4 hours

---

### `exit-risk`

**Criteria:**
- Active alert exists for this token (any previous type ≥ `watch`)
- `P_failure` ≥ 0.65 (significant increase from prior evaluation)
- OR critical risk flag newly triggered (liquidity drop, deployer exit, holder dump)

**Meaning:** A previously monitored token is now showing strong failure signals. This is a warning to those holding or watching this token. Not a guarantee of failure — but conditions have materially worsened.

**Priority:** High. Always delivered regardless of notification rate limits.

**Expiry:** 15 minutes (re-evaluated frequently when conditions are this volatile)

---

### `discard`

**Criteria:**
- `P_failure` ≥ 0.80
- OR confirmed rug event detected
- OR `net_potential` < 0.10 (negligible opportunity signal)

**Meaning:** Opportunity is effectively eliminated. Strong failure signals or confirmed failure event.

**Note:** `discard` is not necessarily permanent. A token can be discarded due to rug risk signals, then re-evaluated if conditions change. However, once a confirmed rug event is detected, the token should not be un-discarded.

**Expiry:** Immediate retirement of prior alerts

---

### `ignore`

**Criteria:**
- `net_potential` < 0.25
- AND `P_failure` < 0.65 (not high enough risk to warrant any alert)
- No active prior alert exists

**Behavior:** No alert record is created in the output. Token is logged in the scoring registry but generates no user-facing output.

---

## Risk Flag Taxonomy

Every alert type ≥ `verify` must include applicable risk flags:

| Flag | Trigger Condition |
|---|---|
| `CRITICAL_RUG_RISK` | rug_risk_score > 0.75 |
| `HIGH_HOLDER_CONCENTRATION` | top5_pct > 50% |
| `WALLET_CLUSTERING` | clustering_coefficient > 0.60 |
| `NEW_DEPLOYER` | deployer wallet age < 48 hours |
| `KNOWN_BAD_DEPLOYER` | deployer in known bad-actor list |
| `UNLOCKED_LIQUIDITY` | Liquidity entirely unlocked |
| `LOW_LIQUIDITY` | Total liquidity < $5K USD equivalent |
| `MINT_AUTHORITY_ACTIVE` | Mint authority not renounced |
| `FREEZE_AUTHORITY_ACTIVE` | Freeze authority enabled |
| `SUSPICIOUS_VOLUME` | momentum_quality < 0.35 |
| `WASH_TRADE_PATTERN` | Specific wash trade detection signal |
| `LOW_CONFIDENCE` | confidence_score < 0.50 |
| `NARRATIVE_AMBIGUOUS` | Multiple narratives within 0.15 of each other |
| `COPYCAT_LIKELY` | og_score < 0.35 |
| `NARRATIVE_DECLINING` | Narrative state = DECLINING |
| `TIMING_LATE` | timing_quality < 0.30 |
| `DATA_GAP` | Missing data for one or more dimensions |

---

## Required Fields per Alert

All alert types (except `ignore`) must include:

```
{
  alert_id: string,
  token_address: string,
  token_name: string,
  token_symbol: string,
  narrative_id: string,
  narrative_name: string,
  alert_type: string,
  net_potential: float,
  P_potential: float,
  P_failure: float,
  confidence_score: float,
  dimension_scores: {
    narrative_relevance: float,
    og_score: float,
    rug_risk: float,
    momentum_quality: float,
    attention_strength: float,
    timing_quality: float
  },
  risk_flags: [string],
  reasoning: string,
  created_at: timestamp,
  expires_at: timestamp,
  re_eval_triggers: [string],
  status: "ACTIVE" | "RETIRED",
  history: [{ timestamp, previous_type, previous_scores, change_reason }]
}
```

No field in this schema may be omitted. If a value is unavailable, it must be explicitly marked as `null` with a corresponding `DATA_GAP` flag.

---

## Alert Escalation and Downgrade Rules

| From | To | Condition | Re-deliver? |
|---|---|---|---|
| `watch` | `high-potential-watch` | Score upgrade | Yes |
| `high-potential-watch` | `possible-entry` | Score upgrade + P_failure drops | Yes |
| `possible-entry` | `take-profit-watch` | Timing degraded, opportunity maturing | Yes |
| Any | `exit-risk` | P_failure spikes or critical trigger | Yes (always) |
| Any | `discard` | Confirmed failure signal | Yes |
| `high-potential-watch` | `watch` | Score degraded | Only if change > 1 tier |
| Any | `verify` | Evidence quality drops significantly | Yes |
