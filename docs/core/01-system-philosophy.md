# System Philosophy

These are the non-negotiable principles of this system. They are not preferences. They are constraints. Every design decision, every implementation choice, every new feature must be evaluated against them.

---

## 1. Probabilistic, Not Deterministic

This system produces probability estimates, not certainties.

- We do not say "this token will pump."
- We say "given the available evidence, there is an estimated X% probability of a remaining opportunity window, with Y confidence in that estimate."
- All probability values are model outputs based on weighted heuristics. They are not ground truth.
- Confidence scores reflect the quality of evidence, not the quality of the opportunity.

**Implication:** Never build a feature that implies or outputs a guarantee. Never display a probability without also displaying a confidence indicator and a disclaimer that this is an estimate.

---

## 2. Adversarial by Default

Assume the environment is trying to deceive the system.

This includes:
- Fake social engagement (bots, coordinated posting)
- Wash trading on-chain (fake volume, fake momentum)
- Copycat tokens designed to capture attention from the OG
- Inflated holder counts from airdrop farming wallets
- Manufactured news or narrative seeding
- Shill campaigns in Telegram/Discord/X

**Implication:** No data source is trusted by default. Every signal requires corroboration or must be discounted. The system should be harder to fool than a human scanning manually, not easier.

---

## 3. Explainability is Mandatory

Every alert must decompose into its reasons. There must be no output that cannot be traced back to specific inputs and logic.

- A score of 0.82 must come from: "narrative score X, momentum score Y, rug risk score Z, combined as follows..."
- An alert classification must map directly to threshold logic
- A confidence score must show which inputs were available vs. missing

**Implication:** Do not use LLMs as black boxes for scoring decisions. If an LLM is used, its output must be validated against structured logic and the reasoning must be logged.

---

## 4. Deterministic Logic First, Agents Optional

Start with explicit, deterministic rules. Use LLMs or agents only when:

- The task is genuinely ambiguous or requires natural language understanding (e.g., matching a token name to a cultural reference)
- Deterministic logic has been exhausted
- The agent's output is validated, not trusted blindly

**Implication:** A scoring function with 6 weighted dimensions is better than a prompt that asks an LLM to "rate this token." The former is auditable. The latter is unpredictable.

---

## 5. Fail Safely

When the system lacks sufficient data, it must not produce confident-looking outputs. It must either:
- Downgrade confidence explicitly
- Defer the evaluation
- Output a "data insufficient" state rather than a guess

**Implication:** Missing data is not treated as neutral. A missing rug risk signal should increase default risk, not leave it at zero.

---

## 6. Timing Awareness

This is a real-time system. The relevance of any evaluation decays over time. A signal valid at T+0 may be meaningless at T+4 hours.

- Every alert has an expiry or re-evaluation trigger
- Every probability estimate carries an implicit timestamp of validity
- Stale data must be flagged as stale, not treated as fresh

**Implication:** Do not cache evaluation results indefinitely. Build freshness tracking into the data model from the start.

---

## 7. No Scope Creep Into Trading

This system is an intelligence and alerting layer. It does not:
- Execute trades
- Manage positions
- Calculate position sizing
- Provide stop-loss or take-profit recommendations

The moment any component begins to imply trade execution logic, it has violated scope. Alerts are inputs to a human (or downstream system). They are not instructions.

---

## 8. Minimal Surface Area for Harm

This system deals with a high-risk asset class. The design must:
- Never claim a token is safe
- Never imply that following an alert will result in profit
- Display risk flags prominently, not buried
- Make the uncertainty of every output visible

**Implication:** Alert formatting must always include risk flags. Confidence scores must always accompany probability estimates. The word "safe" is prohibited in system outputs.

---

## 9. Documentation Is the Source of Truth

Code implements the documentation. The documentation defines the system.

- If the documentation and the code disagree, the documentation is right until the documentation is explicitly updated
- No implementation detail should exist without a doc that explains why it was chosen
- Implementations are changeable; principles are not

**Implication:** Before writing new code, check whether the doc describes it. If it doesn't, write the doc first.

---

## 10. Calibrated Humility About Memecoins

Memecoins are a novel, chaotic, and often irrational market. The system must:

- Accept that good evaluations still fail
- Accept that bad evaluations sometimes succeed
- Not overfit to historical patterns that may not repeat
- Not pretend the model is more accurate than it has been measured to be

The correct posture is: "We are identifying conditions that have historically correlated with opportunity. We cannot guarantee they will continue to do so."

---

## Summary Table

| Principle | Core Rule |
|---|---|
| Probabilistic | Never imply certainty |
| Adversarial | Never trust a signal without corroboration |
| Explainable | Every output must decompose into reasons |
| Deterministic-first | Rules before agents |
| Fail-safe | Missing data increases risk estimate |
| Timing-aware | All outputs have expiry |
| No trading scope | Alerts only, no execution logic |
| Minimal harm surface | Risk flags always visible |
| Docs are truth | Write the doc before the code |
| Calibrated humility | Acknowledge model limitations |
