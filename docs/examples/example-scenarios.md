# Example Scenarios

Five real-world scenarios traced end to end through the system. Each scenario illustrates a different pattern the system must handle correctly.

---

## Scenario 1: Clean OG Token on Strong Narrative

**Setup:** A major tech company releases a widely anticipated product. Within 4 minutes, `$TECHLAUNCH` appears on Pump.fun. It's the first token in this namespace. The deployer wallet is new but clean. Social discussion about the product launch is across multiple platforms. No suspicious on-chain activity.

**System flow:**

1. **T+0:** Product announcement. Search trends spike. News articles begin publishing. `EventRecord` created: EMERGING state, attention 0.88, 3 source types.

2. **T+4min:** `$TECHLAUNCH` detected on Pump.fun. `TokenRecord` registered. Supplementary chain data fetch queued.

3. **T+6min:** Chain data arrives. Deployer: new wallet, no prior deployments. Holder concentration: top 5 hold 31% (acceptable). Liquidity: $3,400 USD, unlocked. No other tokens in namespace yet.

4. **T+7min:** Correlation engine: exact match on anchor term `TECHLAUNCH`. Match confidence: 0.96. `TokenNarrativeLink` created. OG rank: 1 (only token in namespace).

5. **T+9min:** Scoring:
   - Narrative relevance: 0.89 (high match + multi-source)
   - OG score: 0.94 (first, exact match, now seeing cross-source mentions)
   - Rug risk: 0.29 (new deployer is a flag, but low concentration and no other risk signals)
   - Momentum: 0.71 (organic early trading pattern)
   - Attention: 0.88 (strong multi-source)
   - Timing: 0.91 (very early in EMERGING narrative)
   - P_potential: 0.83, P_failure: 0.24, net_potential: 0.63, confidence: 0.79

6. **T+10min:** Alert classified: `possible-entry`. Delivered immediately to configured channels.

7. **T+2h:** Scheduled re-evaluation. Narrative now PEAKING (velocity slowing). Timing quality: 0.62. net_potential: 0.52. Alert updated to `high-potential-watch`. No re-delivery (1-tier downgrade).

8. **T+5h:** Narrative entering DECLINING. Timing quality: 0.28. net_potential: 0.38. Alert updated to `take-profit-watch`. Re-delivered (lifecycle signal).

9. **T+8h:** Narrative DEAD. net_potential: 0.12. Alert retired. Retirement reason: narrative_dead.

**System performed correctly.** Early detection, clean alert, lifecycle tracked, graceful retirement.

---

## Scenario 2: Copycat Namespace Attack

**Setup:** Same tech announcement as Scenario 1. But within 12 minutes, 8 more tokens are deployed: `$TECHLAUN`, `$TECH2`, `$TECHLAUNCHV2`, `$TECHCOIN`, `$TLAUNCH`, `$LAUNCH`, `$TECH`, and `$TECHLAUNCHSOL`. All by 3 different deployer wallets (one wallet deployed 5 of them).

**System flow:**

1. All 8 tokens registered as they appear. Supplementary data shows: 5 of them share a deployer. Those 5 deployer wallets are all funded from the same source wallet.

2. Correlation engine matches all 8 to the same narrative. Confidence varies:
   - `$TECHLAUN`: 0.87 (abbreviation match)
   - `$TECHLAUNCHV2`: 0.88 (V2 suffix stripped, exact match)
   - `$TECHCOIN`: 0.82 (suffix stripped, exact match)
   - Others: 0.40–0.65 (related term or partial match)

3. OG resolver receives all 8 + original `$TECHLAUNCH`:
   - `$TECHLAUNCH`: og_score 0.94, og_rank 1 (already had cross-source mentions)
   - `$TECHLAUNCHV2`: og_score 0.51, og_rank 2 (exact name match but 8 minutes late)
   - `$TECHCOIN`: og_score 0.44, og_rank 3
   - 5 from same-deployer cluster: og_score 0.15–0.22, og_rank 5–9 (shotgun-copycat pattern detected)

4. 5 same-deployer tokens get `SHOTGUN_COPYCAT_PATTERN` flag. They score high on rug risk (deployer multi-launcher, funded from same source). All 5 classified as `discard` due to P_failure > 0.80.

5. `$TECHLAUN` and `$TECHLAUNCHV2`: receive `COPYCAT_LIKELY` flag (og_score < 0.40). Classified as `watch` with moderate risk flags.

6. Original `$TECHLAUNCH` unaffected — already has `possible-entry` alert from Scenario 1.

**System performed correctly.** OG identified. Copycats flagged. Shotgun copycats discarded. Namespace pollution handled.

---

## Scenario 3: Strong Narrative, Weak Token

**Setup:** A famous celebrity makes a viral statement that becomes a major meme. Token `$CELEBQUOTE` launches 6 minutes later. However: deployer wallet has 12 prior deployments with 9 known to have rugged. Top 3 wallets hold 82% of supply. Liquidity is $800 USD.

**System flow:**

1. Token registered. Chain data fetch reveals deployer history: 12 deployments, 9 with sudden liquidity removal events. This deployer appears on a community bad-actor list.

2. Rug risk scoring:
   - Deployer risk: 0.95 (known bad deployer from list, pattern of rugs)
   - Concentration risk: 0.90 (top 3 hold 82%)
   - Liquidity risk: 0.75 (low liquidity, single provider)
   - Rug risk total: 0.88 → **Critical tier**

3. Classification check: `KNOWN_BAD_DEPLOYER` flag is active. Per `docs/rules/decision-rules.md` Rule 3: maximum alert type is `discard` for `KNOWN_BAD_DEPLOYER`.

4. Alert classified: `discard`. Despite excellent narrative scores (narrative relevance: 0.92, attention: 0.91), the deployer flag is a hard override.

5. Alert delivered with explanation: "DISCARD — $CELEBQUOTE: Known bad deployer (9 of 12 prior deployments show rug patterns). Critical rug risk score 0.88. Strong narrative does not offset structural failure indicators."

**System performed correctly.** Strong narrative was not allowed to override critical structural risk. The "Risk Flags Cannot Be Suppressed by Positive Signals" rule held.

---

## Scenario 4: Data Source Degraded

**Setup:** An interesting narrative emerges. Token `$NEWTREND` correlates with it. However, during this period, the social data source is unavailable due to an API outage. Chain data and news sources are available.

**System flow:**

1. Social source adapter returns error. `SourceGap` record opened. Source marked unavailable.

2. Ingestion continues without social data. EventRecord created from news + search trends only (no social signal).

3. Token registered normally. Chain data available.

4. Scoring proceeds with missing social dimension:
   - Attention strength: computed from news + search trends only. `social_source_unavailable` logged in data_gaps.
   - Momentum quality: social-chain alignment sub-score defaults to 0.50 (neutral, cannot assess). Flagged as `data_gap`.
   - Confidence score reduced by ~0.15 due to missing social source (per data completeness formula).

5. Alert generated with `DATA_GAP` risk flag and reduced confidence:
   - Original potential alert type: `high-potential-watch`
   - Confidence: 0.61 (reduced from what would have been ~0.76)
   - Risk flags: `DATA_GAP` (social source unavailable during evaluation)
   - Type still `high-potential-watch` (above `verify` threshold despite lower confidence)

6. When social source recovers (SourceGap record closed), `$NEWTREND` is queued for re-evaluation with complete data.

**System performed correctly.** Degraded gracefully. Alert was generated with appropriate confidence reduction and explicit data gap flagging. Re-evaluation queued for when full data is available.

---

## Scenario 5: Slow Rug Detection During Active Alert

**Setup:** `$SLOWRUG` has an active `high-potential-watch` alert. The deployer begins quietly withdrawing liquidity — 8% per hour over 6 hours. No single event triggers a critical alert.

**System flow:**

1. **T+1h re-evaluation:** Liquidity is 92% of initial. `timing_quality` has declined. Alert type unchanged (`high-potential-watch`).

2. **T+2h re-evaluation:** Liquidity is 85%. Rug risk increased slightly. net_potential: 0.41 (was 0.49). Alert updated silently.

3. **T+3h re-evaluation:** Liquidity is 77%. Rug risk escalating. `UNLOCKED_LIQUIDITY` flag already present. Monitor adds `LIQUIDITY_DECLINING_TREND` flag (new flag: when liquidity trend is consistently negative over multiple re-evaluations).

4. **T+4h re-evaluation:** Liquidity is 70%. Now 30% below initial. `liquidity_drop_critical` trigger threshold reached (> 30% from peak). Immediate re-evaluation triggered.

5. Rug risk score: 0.68 (elevated from accumulated signals). P_failure: 0.62. Alert type changes to `exit-risk`.

6. `exit-risk` alert delivered. History shows the gradual liquidity decline pattern.

**System performed correctly.** Slow rug was caught by the time-series liquidity tracking and the > 30% trigger threshold. Earlier re-evaluations correctly showed declining but pre-threshold conditions. The `LIQUIDITY_DECLINING_TREND` flag provided early warning before the trigger fired.

**Gap identified:** The system took 4+ hours to escalate. For a slow rug, this may be too slow. Consider: lower the liquidity drop trigger threshold (e.g., 20% instead of 30%), or add a "consistent decline over N re-evaluations" trigger. This is an open calibration question.
