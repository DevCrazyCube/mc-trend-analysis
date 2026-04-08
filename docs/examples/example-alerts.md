# Example Alerts

Three fully worked alert examples with all fields populated. These serve as the reference for what correct alert output looks like.

---

## Example 1: `possible-entry` — Strong Narrative, Low Failure Risk

**Scenario:** A major sporting event (heavyweight boxing championship) goes viral. Token `$BRAVADO` launches 8 minutes after the fight ends, named after the winner's victory phrase. First token in the namespace. Strong social corroboration.

```json
{
  "alert_id": "a1b2c3d4-0001",
  "token_address": "So1ana...address1",
  "token_name": "BRAVADO",
  "token_symbol": "$BRAVADO",
  "narrative_id": "n-boxing-championship-viral-oct2024",
  "narrative_name": "Boxing Championship Viral Victory (Oct 2024)",
  "alert_type": "possible-entry",

  "net_potential": 0.63,
  "P_potential": 0.81,
  "P_failure": 0.22,
  "confidence_score": 0.78,

  "dimension_scores": {
    "narrative_relevance": 0.87,
    "og_score": 0.91,
    "rug_risk": 0.22,
    "momentum_quality": 0.74,
    "attention_strength": 0.83,
    "timing_quality": 0.84
  },

  "risk_flags": ["UNLOCKED_LIQUIDITY", "NEW_DEPLOYER"],

  "reasoning": "POSSIBLE-ENTRY — $BRAVADO linked to \"Boxing Championship Viral Victory (Oct 2024)\"\n\nOpportunity signal: net_potential 0.63, P_potential 0.81 driven by strong narrative relevance (0.87) and excellent timing (0.84) — narrative in EMERGING state. Strong OG position (0.91): first token in namespace, 8 minutes after event, 3 independent cross-source mentions.\nRisk signal: P_failure 0.22. Primary risks are unlocked liquidity and new deployer wallet (no rug history, but also no history). Holder concentration acceptable: top 5 hold 28% of supply.\nConfidence: 0.78 — chain data complete, social data from 2 of 3 configured sources.\n\nKey risk flags: UNLOCKED_LIQUIDITY, NEW_DEPLOYER.\nWindow estimate: Narrative EMERGING with strong velocity. Estimated 3–6 hour window based on typical sports-narrative lifecycle.",

  "created_at": "2024-10-15T22:08:00Z",
  "expires_at": "2024-10-15T23:08:00Z",
  "re_eval_triggers": ["liquidity_drop_critical", "attention_decay_50pct", "narrative_dead"],
  "status": "ACTIVE",
  "history": []
}
```

**Notes on this example:**
- `possible-entry` requires `net_potential ≥ 0.60`, `P_failure < 0.30`, `confidence ≥ 0.65` — all met
- Despite risk flags (`UNLOCKED_LIQUIDITY`, `NEW_DEPLOYER`), no critical flags present — `possible-entry` is allowed
- Expiry is 1 hour — this type expires quickly because windows are short
- Reasoning clearly attributes each part of the score

---

## Example 2: `high-potential-watch` with Notable Risk

**Scenario:** A major AI company announces a breakthrough. Token `$NEURONX` launches with strong name alignment. However, deployer wallet shows it has deployed 4 previous tokens (2 of which declined rapidly). Holder concentration is elevated.

```json
{
  "alert_id": "a1b2c3d4-0002",
  "token_address": "So1ana...address2",
  "token_name": "NEURONX",
  "token_symbol": "$NEURONX",
  "narrative_id": "n-ai-neuroscience-announcement-2024",
  "narrative_name": "AI Neuroscience Research Breakthrough (Oct 2024)",
  "alert_type": "high-potential-watch",

  "net_potential": 0.48,
  "P_potential": 0.76,
  "P_failure": 0.37,
  "confidence_score": 0.69,

  "dimension_scores": {
    "narrative_relevance": 0.82,
    "og_score": 0.74,
    "rug_risk": 0.41,
    "momentum_quality": 0.65,
    "attention_strength": 0.78,
    "timing_quality": 0.71
  },

  "risk_flags": ["HIGH_HOLDER_CONCENTRATION", "DEPLOYER_MULTI_LAUNCHER", "UNLOCKED_LIQUIDITY"],

  "reasoning": "HIGH-POTENTIAL WATCH — $NEURONX linked to \"AI Neuroscience Research Breakthrough (Oct 2024)\"\n\nOpportunity signal: net_potential 0.48, P_potential 0.76 driven by strong narrative alignment (0.82) and high attention strength (0.78). Token is probable OG (0.74): first to launch, high name precision. Narrative in EMERGING state.\nRisk signal: P_failure 0.37. Rug risk elevated (0.41) due to holder concentration (top 5 wallets hold 54% of supply) and deployer with history of 4 prior token launches (2 of 4 showed rapid decline patterns). Unlocked liquidity is a structural risk.\nConfidence: 0.69 — all sources available, OG resolution is confident.\n\nKey risk flags: HIGH_HOLDER_CONCENTRATION, DEPLOYER_MULTI_LAUNCHER, UNLOCKED_LIQUIDITY.\nWindow estimate: Narrative EMERGING, estimated 2–4 hour window. Multiple risk flags warrant close monitoring before any position.",

  "created_at": "2024-10-16T09:22:00Z",
  "expires_at": "2024-10-16T11:22:00Z",
  "re_eval_triggers": ["liquidity_drop_critical", "attention_decay_50pct", "holder_dump"],
  "status": "ACTIVE",
  "history": []
}
```

**Notes on this example:**
- `high-potential-watch` requires `net_potential ≥ 0.45`, `P_failure < 0.50` — both met
- `DEPLOYER_MULTI_LAUNCHER` is not a blocking flag (not `KNOWN_BAD_DEPLOYER`) — alert type is allowed
- Risk flags are prominently listed and explained in reasoning
- User must evaluate whether the opportunity is worth the risk profile

---

## Example 3: `exit-risk` — Deteriorating Active Alert

**Scenario:** `$DEEPMIND` previously had a `high-potential-watch` alert (from the event-flow example). 90 minutes later, liquidity drops 52% in 35 minutes. Deployer wallet becomes active. Re-evaluation fires immediately.

```json
{
  "alert_id": "a1b2c3d4-0003",
  "token_address": "So1ana...deepmind-address",
  "token_name": "DEEPMIND",
  "token_symbol": "$DEEPMIND",
  "narrative_id": "n-deepmind-product-launch-oct2024",
  "narrative_name": "Google DeepMind Product Launch (Oct 2024)",
  "alert_type": "exit-risk",

  "net_potential": 0.18,
  "P_potential": 0.71,
  "P_failure": 0.75,
  "confidence_score": 0.81,

  "dimension_scores": {
    "narrative_relevance": 0.91,
    "og_score": 0.87,
    "rug_risk": 0.83,
    "momentum_quality": 0.44,
    "attention_strength": 0.77,
    "timing_quality": 0.42
  },

  "risk_flags": [
    "CRITICAL_RUG_RISK",
    "LIQUIDITY_DROP_CRITICAL",
    "DEPLOYER_WALLET_ACTIVE",
    "HIGH_HOLDER_CONCENTRATION",
    "NEW_DEPLOYER",
    "TIMING_LATE"
  ],

  "reasoning": "EXIT-RISK — $DEEPMIND [PREVIOUSLY: HIGH-POTENTIAL WATCH @ 14:32 UTC]\n\nTrigger: Liquidity dropped 52% in 35 minutes. Deployer wallet active (3 outbound transactions in last 20 minutes).\n\nCondition change: P_failure has increased from 0.31 to 0.75. Rug risk score elevated from 0.38 to 0.83 due to liquidity removal event and deployer activity. Narrative remains strong (0.91) and attention is still present (0.77), but structural failure risk now dominates.\n\nnet_potential: 0.18 (was 0.57). This alert is a WARNING — conditions have materially deteriorated.\n\nConfidence: 0.81 — fresh chain data captured the liquidity event directly.\n\nKey risk flags: CRITICAL_RUG_RISK, LIQUIDITY_DROP_CRITICAL, DEPLOYER_WALLET_ACTIVE.",

  "created_at": "2024-10-15T14:32:00Z",
  "updated_at": "2024-10-15T16:07:00Z",
  "expires_at": "2024-10-15T16:22:00Z",
  "re_eval_triggers": ["liquidity_drop_critical", "deployer_exit"],
  "status": "ACTIVE",
  "history": [
    {
      "timestamp": "2024-10-15T14:32:00Z",
      "previous_type": null,
      "new_type": "high-potential-watch",
      "previous_net_potential": null,
      "new_net_potential": 0.57,
      "change_reason": "initial_alert",
      "trigger": "initial_scoring"
    },
    {
      "timestamp": "2024-10-15T16:07:00Z",
      "previous_type": "high-potential-watch",
      "new_type": "exit-risk",
      "previous_net_potential": 0.57,
      "new_net_potential": 0.18,
      "change_reason": "liquidity_drop_52pct_deployer_wallet_active",
      "trigger": "liquidity_drop_critical"
    }
  ]
}
```

**Notes on this example:**
- Shows full lifecycle: `high-potential-watch` → `exit-risk` with complete history
- `history[]` preserves the initial alert and the state transition
- `exit-risk` is triggered by re-evaluation trigger, not by scheduled expiry
- `P_potential` remains high (narrative is still real) but `P_failure` dominates
- The narrative relevance dimension score hasn't changed — the narrative is still valid. The structural risk changed.
- `CRITICAL_RUG_RISK` flag is present — this would block any future re-classification to `possible-entry`
