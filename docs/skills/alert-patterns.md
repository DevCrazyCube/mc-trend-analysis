# Alert Patterns

This document defines patterns for idempotent alert generation, lifecycle management, and reliable delivery.

---

## Pattern 1: Idempotent Alert Creation

**Problem:** The scoring pipeline may run multiple times for the same token-narrative link (due to re-triggers, retries, or restarts). Each run should produce at most one active alert, not duplicates.

**Pattern:**
1. Before creating an alert, query the alert registry for an existing active alert for the same `token_id`
2. If exists: proceed to update logic (not create)
3. If not exists: create new alert

**The uniqueness key for alerts is `token_id + status = ACTIVE`.** There must be at most one active alert per token at any time.

**Idempotency at delivery:** Even if the alert creation is called twice (race condition, retry), only one alert must exist in the registry. Use database upsert semantics or optimistic locking.

---

## Pattern 2: Alert Type Upgrade vs. Downgrade

Upgrades (moving to a higher-opportunity tier) and downgrades (moving to a lower-opportunity tier) have different delivery behavior.

**Upgrade logic:**
- Update the alert type
- Log the transition in `history[]`
- Always trigger re-delivery

**Downgrade logic:**
- Update the alert type
- Log the transition in `history[]`
- Trigger re-delivery only if the downgrade is significant (configurable: ≥ 2 tier drop, or any drop to `exit-risk` or `discard`)

**Rationale:** Upgrades are always worth notifying. Small downgrades (one tier) may just be normal fluctuation and not worth creating noise.

**Absolute override:** Any transition to `exit-risk` or `discard` always triggers re-delivery, regardless of magnitude.

---

## Pattern 3: Alert History Maintenance

Every time an alert is updated, append to its `history[]` array:

```python
history_entry = {
    "timestamp": now(),
    "previous_type": old_type,
    "new_type": new_type,
    "previous_net_potential": old_net_potential,
    "new_net_potential": new_net_potential,
    "change_reason": reason_string,
    "trigger": trigger_name  # "scheduled_reeval", "liquidity_drop", etc.
}
alert.history.append(history_entry)
```

History is append-only. Never remove entries from `history[]`.

---

## Pattern 4: Expiry Management

Expiry is managed by the Re-evaluation Scheduler (see `docs/architecture/components.md`). The pattern:

1. When creating or updating an alert, set `expires_at = now() + expiry_window(alert_type)`
2. The scheduler queries for alerts where `expires_at <= now() AND status = ACTIVE`
3. For each expired alert: trigger re-evaluation (not automatic retirement)
4. Re-evaluation produces a new `ScoredToken`, which produces either an updated alert or retirement

**Key distinction:** Expiry triggers re-evaluation, not retirement. The alert continues to exist until the re-evaluation determines it should be retired.

**Exception:** If the narrative linked to the alert is `DEAD` and re-evaluation produces a score below all thresholds, then retire immediately.

---

## Pattern 5: Re-evaluation Trigger Handling

Event-based triggers (as defined in `docs/alerting/alert-engine.md`) must be handled carefully to prevent cascading re-evaluations.

**Pattern:**
1. When a trigger event fires (e.g., `liquidity_drop_critical`), queue a re-evaluation task for the affected token
2. Before queuing: check if a re-evaluation is already queued or in progress for this token
3. If yes: do not queue another. The in-progress re-evaluation will use the latest data.
4. If no: queue the re-evaluation with the trigger name attached for logging

**Rate limiting re-evaluations:** A token should not be re-evaluated more than once per 5 minutes unless a `critical` trigger fires. Consecutive triggers within 5 minutes are collapsed into a single re-evaluation.

---

## Pattern 6: Delivery Idempotency

**Problem:** A delivery task may be retried after partial failure. The same alert must not be delivered twice to the same channel.

**Pattern:**
1. Before delivery: record `delivery_attempt` in the `AlertDelivery` table with status `in_progress`
2. Attempt delivery to channel
3. On success: update `AlertDelivery` status to `delivered`
4. On failure: update status to `failed`, schedule retry with backoff
5. Before retry: check if a `delivered` record already exists for this alert + channel — if so, do not re-deliver

**The check in step 5 is the key.** If the task queue retries a delivery task because it thought it failed, the check prevents duplicate delivery.

---

## Pattern 7: Alert Retirement Ceremony

When retiring an alert:

1. Verify retirement is appropriate (re-check classification against current data)
2. Set `status = RETIRED`
3. Record `retired_at = now()`
4. Record `retirement_reason` (narrative_dead, below_threshold, rug_confirmed, manual, etc.)
5. Log the retirement in the audit log
6. If retirement is for an alert that was previously at `possible-entry` or `high-potential-watch`: optionally deliver a retirement notice to channels that received the original alert

**Never delete retired alerts.** Retained retired alerts are calibration data.

---

## Pattern 8: Reasoning String Generation

The `reasoning` field must be generated from structured data, not freehand prose.

**Template pattern:**
```python
def generate_reasoning(alert_type: str, token: Token, narrative: Narrative, scores: ScoredToken) -> str:
    top_positive = get_top_positive_signals(scores, n=2)
    top_risks = get_top_risk_signals(scores, n=2)
    
    reasoning = (
        f"{alert_type.upper()} — ${token.symbol} linked to \"{narrative.description}\"\n\n"
        f"Opportunity signal: net_potential {scores.net_potential:.2f}, "
        f"P_potential {scores.p_potential:.2f} driven by {', '.join(top_positive)}.\n"
        f"Risk signal: P_failure {scores.p_failure:.2f} due to {', '.join(top_risks)}.\n"
        f"Confidence: {scores.confidence_score:.2f} — {get_confidence_note(scores)}.\n\n"
        f"Key risk flags: {', '.join(scores.risk_flags) if scores.risk_flags else 'none detected'}.\n"
        f"Window estimate: {get_window_estimate(scores, narrative)}."
    )
    return reasoning
```

The functions `get_top_positive_signals`, `get_top_risk_signals`, `get_confidence_note`, and `get_window_estimate` are deterministic functions that map score data to human-readable phrases. They use lookup tables or simple logic, not LLMs.

**Testing:** Generate reasoning for known inputs, verify output is accurate and non-misleading.
