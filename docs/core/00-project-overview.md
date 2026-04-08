# Project Overview

## What We Are Building

A real-time trend intelligence and alerting system for tokens launched on Pump.fun and the broader Solana memecoin market.

The system monitors newly launched and actively traded tokens, evaluates their connection to real-world events, narratives, and attention sources, and outputs structured alerts that represent probabilistic assessments of opportunity quality.

It does not trade. It does not promise returns. It identifies moments worth paying attention to.

---

## Core Problem

Memecoin markets are extremely noisy. Thousands of tokens are created daily. Most are worthless, many are scams, a small subset coincide with genuine cultural attention moments that drive price action. The challenge is not finding tokens — it is filtering signal from noise fast enough to be useful.

The additional complexity:
- Canonical tokens are surrounded by dozens of copycats within minutes of launch
- Narratives degrade in relevance rapidly
- On-chain signals can be fabricated
- Social signals are easy to simulate
- Timing windows are short

Humans cannot process this at speed. Naive automation gets fooled. This system is designed to reason about it systematically.

---

## What the System Outputs

The primary output is **alerts** — structured records that describe:

- Which token is under consideration
- What real-world narrative it connects to
- Whether it appears to be original or a copycat
- What structural risk signals are present
- The strength and quality of its momentum
- How strong the external attention is
- Where the token is in its likely lifecycle
- A derived probability estimate of remaining opportunity
- A confidence score based on evidence quality
- The reasoning behind all of the above, in human-readable form

Alerts are not buy/sell signals. They are structured probability estimates with explicit uncertainty.

---

## Who This Is For

This system is designed to support human decision-making, not replace it. The intended user:

- Understands that memecoins are high-risk, speculative assets
- Wants to reduce time spent manually scanning for narratively-relevant tokens
- Can interpret probability estimates and act on them with appropriate judgment
- Accepts that the system will miss some opportunities and include some failures

This system is explicitly not for:
- Automated execution of trades
- Users who cannot tolerate total loss of capital
- Anyone who needs certainty rather than probability

---

## Core Statement of Purpose

> Detect tokens with meaningful narrative backing, estimate their probability of having a remaining opportunity window, surface that estimate with full reasoning, and do so before the window closes.

---

## System Boundaries

**Inside scope:**
- Token discovery and qualification
- Narrative matching and strength estimation
- Authenticity and OG token resolution
- Rug and failure risk estimation
- Momentum quality analysis
- Alert generation and delivery

**Outside scope:**
- Trade execution
- Portfolio management
- Price prediction
- Financial advice
- Any guarantee of outcome

See `docs/core/03-scope-and-non-goals.md` for the full boundary definition.

---

## Key Design Constraints

1. **Speed matters.** Narrative windows are short. Hours, sometimes minutes. The system must evaluate and alert fast.

2. **Adversarial environment.** Assume bad actors are trying to fool the system — through fake social signals, copycat tokens, wash trading, coordinated manipulation. The system must be skeptical by default.

3. **Explainability is required.** Every alert must decompose into reasons. No black-box outputs.

4. **Calibrated uncertainty.** Probabilities are estimates, not facts. The system must never produce false precision.

5. **Documentation-first.** The architecture is stable; implementations are swappable. Docs are the source of truth.

---

## Related Documents

- `docs/core/01-system-philosophy.md` — The principles that govern every design decision
- `docs/architecture/system-architecture.md` — Technical structure
- `docs/intelligence/scoring-model.md` — The evaluation model
- `docs/alerting/alert-types.md` — Output format and taxonomy
