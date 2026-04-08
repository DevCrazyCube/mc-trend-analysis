# Signal Philosophy

This document explains why the system generates alerts the way it does, what an alert means, and what it explicitly does not mean.

---

## An Alert Is Not a Recommendation

The system produces **intelligence signals**, not recommendations. The distinction is not semantic. It has real implications:

A **recommendation** implies:
- The system has evaluated your personal risk tolerance
- The system has considered your portfolio and position size
- The system is advising you to take a specific action
- The system takes some responsibility for what happens if you follow its advice

A **signal** means:
- The system has detected conditions that historically correlate with certain outcomes
- Those conditions are described as precisely as the evidence allows
- What you do with that information is entirely your decision
- The system does not know your circumstances, and it cannot account for factors it cannot observe

Every alert should be read as: *"Here is what we observed. Here is how we assess it. Here is our uncertainty. You decide what to do."*

---

## The Signal-to-Noise Tradeoff

This system is intentionally calibrated toward **signal quality over signal volume**.

It will miss opportunities. That is acceptable.
It will generate false positives. That is expected.
It will never generate an alert claiming certainty. That is non-negotiable.

A system that alerts on everything produces noise, not signal. Users of a noisy system learn to ignore it. The most dangerous outcome is a high-confidence false positive — a clean-looking alert on a rug that successfully fools the model.

The goal is to produce fewer, higher-quality alerts that users can take seriously. Low-tier alerts (`watch`, `verify`) exist to prevent complete information loss — but they are not designed to be acted upon directly.

---

## Why All These Alert Tiers?

**`possible-entry`** is rare and requires convergence across dimensions. It signals the best-case scenario where the evidence aligns.

**`high-potential-watch`** is the primary working tier. Most valuable signals live here. Risk is present (it's always present) but is below the threshold that would overwhelm the opportunity signal.

**`take-profit-watch`** exists because lifecycle awareness matters. An alert from 4 hours ago may no longer represent the same opportunity. This tier acknowledges the passage of time in the narrative window.

**`verify`** is an honesty signal. It says: "we see something interesting but we don't trust our own evidence enough." It prevents the system from falsely elevating uncertain signals to confident alerts.

**`watch`** prevents complete information loss. Some signals are too weak to act on but too notable to discard. Background awareness has value.

**`exit-risk`** serves a different function entirely. It is a warning about a deteriorating situation, not an opportunity signal. It should be treated with urgency.

**`discard`** closes the loop on failed signals. It tells the user that what was previously flagged has failed or is predicted to fail with high confidence.

---

## The Three Worst Things the System Can Do

In order of severity:

### 1. Generate a High-Confidence False Positive on a Rug

This is the most dangerous output. A user acts on a `possible-entry` signal on a token that immediately rugs. This:
- Causes direct financial harm
- Destroys trust in the system
- Is difficult to diagnose and prevent

**Mitigations:** Rug risk is independently weighted with high contribution to P_failure. Critical risk flags block the `possible-entry` tier. The system must never suppress rug signals to improve apparent opportunity scores.

### 2. Produce False Precision

Displaying "net_potential: 67.34%" implies a level of mathematical rigor that does not exist. A user calibrates their behavior to the precision of the output. If the output implies false precision, the user will be over-reliant on a number that does not deserve that reliance.

**Mitigations:** Round all scores to two decimal places. Display confidence alongside every probability. Format reasoning strings that explain uncertainty clearly.

### 3. Create Alert Fatigue

Too many alerts → users start ignoring them → the alerts lose value → the system fails its purpose.

**Mitigations:** Alert tiers with different delivery defaults. Rate limiting in the delivery layer. `watch` and `verify` alerts are low-delivery by default. Only high-tier and risk alerts get immediate delivery.

---

## How to Read an Alert

When reviewing an alert, the correct questions are:

1. **What is the net_potential and confidence?** Is this a strong or weak signal? How much do I trust it?
2. **What are the risk flags?** Are there red flags that independently concern me?
3. **What narrative is this linked to?** Do I independently agree that this is a real trend moment?
4. **What is the timing quality?** Am I early, at peak, or late?
5. **Is there OG ambiguity?** Is this definitely the canonical token or is the namespace contested?
6. **What data is missing?** Is the confidence low because of data gaps? What would I need to verify?

These questions require human judgment. The system provides structured inputs to that judgment — it does not replace it.

---

## What Happens When the System Is Wrong

The system will be wrong. Regularly. That is not a flaw in the system — it is the nature of probabilistic signal in a chaotic market.

Correct behavior when the system is wrong:
1. **Track and log the outcome** — the alert, the timestamp, the subsequent token behavior
2. **Analyze the failure mode** — was it a rug the model missed? A narrative that died faster than expected? A wash-trade the system didn't detect?
3. **Update calibration** — if a dimension systematically over- or under-predicts, adjust weights
4. **Do not remove the signal** — a signal that fails sometimes is still useful if it succeeds more often than chance

Incorrect behavior when the system is wrong:
- Claiming the model is broken after a single failure
- Adding ad-hoc rule overrides that fix one case but break the general model
- Reducing confidence displays to hide uncertainty ("this looks better without the confidence score")

---

## The Relationship Between Signals and Outcomes

The system aims for **calibration**, not accuracy in the traditional sense.

- A well-calibrated system where `net_potential = 0.60` produces opportunity windows 60% of the time is doing its job correctly — even though 40% of those alerts fail.
- An "accurate" system that hits a high overall success rate by only alerting on near-certainties is missing most of the actual opportunities.

Calibration means: the numbers mean what they say. If we say 0.60, we should see opportunity windows about 60% of the time for that score band.

Achieving calibration requires sustained measurement, honest assessment of outcomes, and willingness to update the model. It is not achievable at launch — only through operation.
