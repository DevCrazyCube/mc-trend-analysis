# Notification Strategy

This document defines how alerts are delivered, what gets delivered vs. suppressed, and how to prevent alert fatigue.

---

## Delivery Principles

1. **Signal quality over volume** — fewer, better alerts are more useful than many marginal ones
2. **Context always included** — formatted alerts must include risk flags and confidence, never just the opportunity signal
3. **Urgency matters** — high-priority and risk alerts bypass normal rate limiting
4. **Idempotency** — delivering the same alert twice is worse than missing one delivery

---

## Alert Delivery Matrix

| Alert Type | Default Delivery Mode | Re-delivery on Update | Notes |
|---|---|---|---|
| `possible-entry` | Immediate push | Yes, always | Highest priority |
| `high-potential-watch` | Immediate push | Yes if type changes | Core alert type |
| `take-profit-watch` | Immediate push | Yes | Lifecycle signal |
| `verify` | Digest (non-push) | No | Requires human review, not urgent |
| `watch` | Digest (non-push) | No | Background signal only |
| `exit-risk` | Immediate push | Yes, always | Bypasses all rate limits |
| `discard` | Optional (configurable) | No | Closes prior alerts |
| `ignore` | None | N/A | Not delivered |

---

## Delivery Channels

The system supports multiple output channel types. Specific channel implementations are in `docs/implementation/current-approach.md`.

**Channel categories:**

| Category | Examples | Delivery Speed | Use For |
|---|---|---|---|
| Push notification | Telegram, Discord, webhook | Immediate | Tier 1, exit-risk |
| Message queue | Any queue-based consumer | Near-immediate | Tier 1–2, integration |
| Digest feed | Email, RSS-like summary | Delayed (hourly or on-demand) | Tier 3, background monitoring |
| Persistent log | Database, file | Always | All alerts, for audit |

Every alert is always written to the persistent log regardless of other delivery configuration.

---

## Rate Limiting

Rate limiting prevents channel flooding when many tokens trigger simultaneously during a viral narrative moment.

### Per-Channel Rate Limits (configurable defaults)

| Channel Type | Rate Limit | Burst Limit |
|---|---|---|
| Push (Telegram/Discord) | 6 alerts per 10 minutes | 3 simultaneous bursts |
| Webhook | 20 alerts per minute | 10 simultaneous |
| Digest | Not rate limited | N/A |
| Persistent log | Not rate limited | N/A |

### Rate Limit Priority Queue

When rate limiting kicks in, alerts are queued and prioritized:

1. `exit-risk` — always delivered immediately, bypasses queue
2. `possible-entry` — highest priority in queue
3. `high-potential-watch` — second priority
4. `take-profit-watch` — third priority
5. `verify` / `watch` — lowest priority, may be dropped from queue if queue fills

Dropped queue items are still written to the persistent log.

---

## Alert Formatting

### Push Alert Format (Telegram/Discord example)

```
🟡 HIGH-POTENTIAL WATCH — $DEEPMIND
━━━━━━━━━━━━━━━━━━━━━━━━
Narrative: Google DeepMind Product Launch
net_potential: 0.57 | confidence: 0.74
P_potential: 0.83 | P_failure: 0.31

⚠️ Risk Flags: HIGH_HOLDER_CONCENTRATION, NEW_DEPLOYER

Reasoning: Strong narrative match (0.91) to trending DeepMind news. 
First mover in namespace. Holder concentration reduces net potential 
despite strong narrative. Timing: EMERGING (window ~2–5 hrs estimated).

🔗 Address: [contract address]
🕐 Expires: in 2h | Created: 14:32 UTC
```

**Rules for push format:**
- Alert type always at top
- Net potential and confidence always together
- Risk flags always visible — never hidden or below the fold
- Reasoning always included (not abbreviated)
- Address always included for verification
- Timestamp and expiry always included

---

### Exit-Risk Alert Format

```
🔴 EXIT-RISK — $DEEPMIND [PREVIOUS: HIGH-POTENTIAL WATCH]
━━━━━━━━━━━━━━━━━━━━━━━━
Trigger: Liquidity dropped 47% in 38 minutes
P_failure: 0.72 (was 0.31) | net_potential: 0.23 (was 0.57)

Condition change: Holder dump pattern detected simultaneously with 
liquidity movement. Deployer wallet active.

Address: [contract address]
Time: 16:15 UTC | Previous alert at: 14:32 UTC
```

Exit-risk alerts must include:
- What changed (specific trigger)
- Before/after score comparison
- Reference to the previous alert time

---

### Digest Format

For `verify` and `watch` alerts delivered in digest mode:

```
DIGEST — 4 signals from last 2 hours (14:00–16:00 UTC)

1. WATCH — $MOONCAT | narrative: Viral Cat Video | net: 0.27 | conf: 0.61
2. VERIFY — $GROK2 | narrative: xAI Product Launch | net: 0.38 | conf: 0.42 | ⚠ LOW_CONFIDENCE
3. WATCH — $BBHUMP | narrative: Political Meme Cycle | net: 0.29 | conf: 0.55
4. VERIFY — $HAWK | narrative: AMBIGUOUS (Military/Bird) | net: 0.36 | conf: 0.39 | ⚠ NARRATIVE_AMBIGUOUS

[Full details available in alert log]
```

Digest format is a summary only. Full alert details are always available in the persistent log.

---

## Deduplication

Before delivering any alert, the delivery layer checks:

1. Has this exact alert (same alert_id, same type) already been delivered to this channel?
2. If yes: do not re-deliver unless the alert type has changed or a re-delivery trigger fired
3. If a duplicate would be delivered within 5 minutes of the original: hold it

Deduplication is idempotent: deliver the same alert to the same channel at most once per alert state.

---

## Alert Expiry Notifications

When an alert expires without being resolved (neither discarded nor upgraded), the delivery layer optionally sends an expiry notice to indicate the alert is no longer active.

Default: only send expiry notices for `possible-entry` and `exit-risk` alerts. Do not send for `watch`/`verify`.

---

## Configuration

The following delivery parameters are configurable (not hardcoded):

- Rate limits per channel
- Which alert types get push vs. digest delivery
- Whether expiry notifications are sent
- Maximum alerts per time window per channel
- Which channels are active

Configuration lives in `docs/implementation/current-approach.md` for the current implementation and in the system configuration layer. It does not live in this document.
