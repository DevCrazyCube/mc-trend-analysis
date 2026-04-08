# CLAUDE.md — Instructions for Claude Sessions in This Repository

This file governs how Claude Code sessions should behave when working in this repository. Read this before doing anything else in a new session.

---

## What This Repo Is

A real-time trend intelligence and alerting system for Pump.fun / Solana memecoins.

The system detects narrative-relevant tokens, evaluates them across six dimensions, and produces structured probability-based alerts. It is an intelligence layer — not a trading system.

**Start here before reading code:**
1. `docs/core/00-project-overview.md` — what we're building
2. `docs/core/01-system-philosophy.md` — the principles that cannot change
3. `docs/architecture/system-architecture.md` — how it's structured
4. `docs/intelligence/scoring-model.md` — how it thinks

---

## Documentation Is the Source of Truth

This is not a metaphor. If the documentation and the code disagree, the documentation is right until the documentation is explicitly updated.

**Before writing code:**
1. Find the doc that describes the behavior you're implementing
2. If no doc exists: write the doc first, then write the code
3. If the doc is unclear: clarify the doc before writing code

**Before changing behavior:**
1. Find the doc that defines the current behavior
2. Understand why it is the way it is (read the surrounding context)
3. Update the doc first
4. Then update the code to match

---

## Rules You Must Follow in Every Session

### 1. No Hardcoded Configuration Values

Weights, thresholds, API endpoints, rate limits, and interval values all live in configuration, not in code. If you find them hardcoded, move them to configuration.

Defined in: `docs/rules/engineering-rules.md` Rule 2

---

### 2. Deterministic Logic First, Agents Second

Do not use an LLM or agent for any task that can be expressed as deterministic logic with acceptable accuracy. Before introducing an LLM call, read:

`docs/implementation/agent-strategy.md`

Prohibited LLM uses (non-negotiable):
- Scoring any dimension
- Classifying alert types
- Rug risk assessment
- OG determination

Approved uses:
- Layer 4 semantic narrative matching (with validation and fallback)
- Reasoning summary enhancement (optional, low priority)

---

### 3. Never Claim Certainty

No generated text, comment, variable name, function name, or output may imply that a token is "safe," that a rug is "guaranteed," or that an alert is a "recommendation."

Examples of prohibited language:
- `is_safe` (use `has_low_risk_signals`)
- `will_pump` (use `high_potential_score`)
- `guaranteed_opportunity` (nothing of the kind exists)
- `safe_to_trade` (absolutely not)

---

### 4. Never Suppress Risk Flags

Risk flags must be visible in all alert outputs. They may not be:
- Hidden behind a "more details" collapse
- Moved below the opportunity score without clear visual hierarchy
- Omitted from delivery formats for brevity

Defined in: `docs/alerting/alert-types.md`, `docs/alerting/notification-strategy.md`

---

### 5. All State Transitions Are Logged

When any entity changes status, the transition must be logged with: previous state, new state, timestamp, reason.

---

### 6. Missing Data Is Conservative, Not Zero

When data is unavailable:
- Do not default to 0
- Do not default to best case
- Apply the conservative defaults defined in `docs/intelligence/probability-framework.md`
- Add the missing field to `data_gaps[]`

---

### 7. Schema Changes Require Documentation Updates

Any change to the record schemas defined in `docs/implementation/data-model.md` or `docs/ingestion/normalization.md` requires updating those docs in the same commit as the code change.

---

## How to Navigate This Codebase

### To understand the scoring model:
Read `docs/intelligence/scoring-model.md` → `docs/intelligence/probability-framework.md`

### To understand a specific dimension:
- Narrative: `docs/intelligence/narrative-linking.md`
- OG: `docs/intelligence/og-token-resolution.md`
- Rug risk: `docs/intelligence/rug-risk-framework.md`
- Momentum: `docs/intelligence/momentum-analysis.md`

### To understand how alerts work:
`docs/alerting/alert-engine.md` → `docs/alerting/alert-types.md`

### To understand the data pipelines:
`docs/architecture/pipelines.md` → `docs/architecture/event-flow.md`

### To understand what sources we use:
`docs/ingestion/source-types.md` → `docs/research/source-catalog.md`

### To understand implementation choices:
`docs/implementation/current-approach.md` (these are changeable)

### To understand what not to build:
`docs/core/03-scope-and-non-goals.md` → `docs/rules/anti-overengineering.md`

---

## Approach to Making Changes

### Small targeted changes
Make the change. Update the relevant doc in the same commit. Write the test. Done.

### Behavior changes (algorithm, weights, thresholds)
1. Read the current doc thoroughly
2. Understand why the current design is the way it is
3. Update the doc with the change and rationale
4. Update the code
5. Run tests

### Large refactors
Do not perform large refactors without explicit user direction. If a refactor seems necessary, describe what you see and why, and ask before proceeding. Large refactors without justification are prohibited.

### New features
Find the relevant doc first. If the feature isn't described in a doc, don't implement it. Discuss it with the user, agree on the doc first.

---

## Testing Requirements

Any change to:
- Scoring logic (any dimension computation)
- Probability formulas
- Alert classification thresholds
- OG resolution logic
- Rug risk assessment

...requires unit tests that verify correct output for known inputs. Do not skip testing for "obvious" logic — probability formulas contain bugs when seemingly obvious.

---

## Things This System Is Not

Repeat these to yourself if you find yourself building them:

- Not a trading bot
- Not a portfolio manager
- Not a financial advisor
- Not a price predictor
- Not a safety guarantor
- Not a certainty engine

If you're building something that looks like one of these, stop and re-read `docs/core/03-scope-and-non-goals.md`.

---

## When You're Unsure

If you're uncertain whether a change is in scope, or whether an approach violates the system philosophy, do not guess. Ask explicitly: "Is this in scope?" or "Does this violate the philosophy in X way?"

The documentation is extensive for a reason. If something isn't covered, that's a gap to be filled — not a license to invent.
