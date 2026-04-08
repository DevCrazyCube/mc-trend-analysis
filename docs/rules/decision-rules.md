# Decision Rules

These rules govern scoring thresholds, alert classification decisions, and how the system behaves at decision boundaries.

---

## Rule 1: Conservative Threshold Tie-Breaking

When a score falls exactly on a classification threshold boundary, always classify downward (more conservative).

Example: `net_potential = 0.45` and the threshold for `high-potential-watch` is `≥ 0.45`.
- The token qualifies. But if confidence is exactly 0.55 (the minimum for `high-potential-watch`), classify as `verify`, not `high-potential-watch`.

When in doubt between two classifications, choose the safer one. False negatives (missing opportunities) are better than false positives (alerting on rugs).

---

## Rule 2: Risk Flags Cannot Be Suppressed by Positive Signals

A high narrative relevance score does not reduce rug risk. A strong OG signal does not reduce holder concentration risk. Scores in separate dimensions are independent.

Specifically: `P_potential` and `P_failure` are computed separately. A high `P_potential` does not reduce `P_failure`. A token can be both a strong narrative play AND a probable rug — and that combination must be represented in the alert, not hidden.

Any component that attempts to use positive dimension scores to offset negative risk signals is in violation of this rule.

---

## Rule 3: Critical Risk Flags Block Certain Alert Types

The following risk flag combinations prevent a token from being classified above `verify`, regardless of `net_potential`:

| Risk Flag Combination | Maximum Alert Type |
|---|---|
| `CRITICAL_RUG_RISK` | `verify` (even if net_potential qualifies for higher) |
| `KNOWN_BAD_DEPLOYER` | `discard` |
| Confirmed rug event (on-chain) | `discard` |
| `FREEZE_AUTHORITY_ACTIVE` + `MINT_AUTHORITY_ACTIVE` | `verify` |

These are hard caps. They cannot be overridden by configuration. They exist because the human harm from alerting on these token types at high tiers is too significant.

---

## Rule 4: Missing Data Defaults Are Conservative

When a dimension cannot be scored due to missing data:
- Rug risk default: 0.50 (not zero)
- All other dimensions: 0.40 (below average)

The rationale: missing data in an adversarial environment is suspicious. A deployer who hides data, a source that is unavailable, or a field that cannot be fetched — all of these reduce our confidence and should increase our caution.

This is documented in `docs/intelligence/probability-framework.md` and `docs/intelligence/rug-risk-framework.md`. Code must implement this precisely.

---

## Rule 5: Re-evaluation Is Mandatory, Not Optional

When any of the defined re-evaluation triggers fire (see `docs/alerting/alert-engine.md`), the re-evaluation must happen. There is no "skip for performance" logic allowed.

If re-evaluation is too slow for the trigger conditions, the correct solution is to optimize re-evaluation, not to skip it.

**Trigger conditions that cannot be skipped:**
- `liquidity_drop_critical`
- `deployer_exit`
- `KNOWN_BAD_DEPLOYER` flag newly applied

---

## Rule 6: Probability Values Must Not Be Displayed Without Confidence

In any user-facing output, a probability value (`net_potential`, `P_potential`, `P_failure`) must always appear alongside its `confidence_score`. They are always displayed as a pair.

The format is specified in `docs/alerting/notification-strategy.md`. Deviations from this format are not allowed without updating the doc.

---

## Rule 7: Alert Types Are Not Negotiable

The eight alert types defined in `docs/alerting/alert-types.md` are the complete taxonomy. There are no "custom" or "special" alert types created at runtime.

If a new alert type is needed, add it to `docs/alerting/alert-types.md` first, then implement it. Do not create ad-hoc types in code.

---

## Rule 8: Scoring History Is Never Deleted

ScoredToken records are append-only. When a token is re-evaluated, a new ScoredToken record is created. The previous record remains.

This rule exists because calibration analysis requires the full history of scores over time. Deleting or overwriting scores makes it impossible to understand how the model's predictions compared to reality.

---

## Rule 9: Narrative Dead = Re-evaluate All Linked Tokens

When a narrative transitions to `DEAD` state, all active alerts linked to that narrative must be re-evaluated within one polling cycle.

This is not a suggestion. Alerts based on dead narratives are stale alerts. They must be updated or retired.

---

## Rule 10: No Inference of "Safe"

No component may produce output that implies or states a token is "safe," "low risk," or "secure."

Acceptable phrasings:
- "Low observed risk signals" (describes what we can and cannot see)
- "No critical risk flags detected" (specific and bounded)
- "Rug risk score: 0.22 — few observable risk indicators" (honest about what it measures)

Unacceptable phrasings:
- "Safe token"
- "Low risk investment"
- "No rug risk"
- "Secure contract"

This rule applies to all generated text including reasoning strings, alert bodies, and any user-facing copy.

---

## Rule 11: Score Weights Are Documented Before They Are Changed

Before changing any dimension weight in the probability formula:
1. Update `docs/intelligence/probability-framework.md` with the new weights and the rationale
2. Document the old weights in that same update
3. Run the updated weights against historical scored tokens to check for unexpected behavior
4. Deploy

Changing weights in code without updating the doc breaks the documentation-as-truth principle.

---

## Rule 12: OG Resolution Does Not Suppress Copycats

Copycats are not suppressed from scoring. They receive lower OG scores, which reduces their `P_potential`, but they go through the full pipeline.

The rationale: in ambiguous cases, what looks like a copycat may be the community-adopted token. The system makes probabilistic estimates, not definitive classifications. Suppressing copycats entirely would mean missing legitimate tokens.
