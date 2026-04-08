# Agent Strategy

This document defines when agents and LLMs are used in this system, what they are explicitly not used for, and how their outputs are constrained.

---

## Default Position: Deterministic First

Agents (LLM-powered reasoning systems) introduce:
- Non-determinism (same input → different output on different runs)
- Latency (API round-trips, inference time)
- Cost (per-token pricing)
- Opacity (hard to audit why a specific output was produced)
- Fragility (model updates can change behavior without code changes)

The system starts from a position of: **use deterministic logic everywhere it is sufficient, and introduce LLM/agent logic only where deterministic approaches genuinely fall short.**

"Genuinely fall short" means: the task requires natural language understanding, semantic reasoning, or flexible interpretation that cannot be captured by rules with acceptable accuracy.

It does not mean: "it would be faster to write a prompt than to write the rules."

---

## Approved Uses of LLMs

### 1. Semantic Narrative Matching (Layer 4)

**Use case:** A token name has no exact or near-exact match to any narrative anchor term, but a human would clearly see the connection.

**Example:**
- Token `$GALAXY` launched during a NASA discovery announcement about a distant galaxy
- Deterministic layers (exact, abbreviation, related-term) all fail to match "NASA" or "astronomy" to "GALAXY"
- An LLM can recognize that "galaxy" is a plausible token name referencing a NASA galaxy story

**How it is used:**
- LLM receives: token name, token symbol, top 10 active narrative summaries
- LLM returns: structured JSON `{ match_found: bool, narrative_id: string | null, confidence: float, rationale: string }`
- Output is validated: confidence must be between 0 and 1, narrative_id must exist in the registry
- Output confidence is capped at 0.40 (semantic matches are inherently less reliable than deterministic ones)
- LLM output alone cannot produce a score above `verify` tier — must be corroborated

**Constraints:**
- Prompt is fixed and versioned — not dynamically constructed per call
- Input is sanitized before inclusion in the prompt
- Output is fully structured — no free-form prose that feeds into scoring
- All inputs and outputs are logged

---

### 2. Reasoning Summary Generation

**Use case:** The system generates human-readable reasoning strings for alerts (see `docs/alerting/alert-engine.md`).

**Current approach:** Reasoning is generated deterministically from a template populated with score values. No LLM needed.

**LLM as enhancement (optional, later):** An LLM could improve the quality and readability of reasoning summaries, making them feel less templated. This is low priority. The data must always come from the structured scores, not from LLM interpretation.

**If implemented:**
- LLM receives: structured score data and template
- LLM returns: prose narrative summary
- The summary must match the structured data exactly — any divergence is a bug
- Template-generated fallback always available if LLM fails

---

### 3. Adversarial Pattern Detection (Future, Not Current)

**Use case:** Detecting novel manipulation patterns that haven't been seen before and can't be captured by existing rules.

**Status:** Not in current implementation. Deterministic rules cover known patterns. LLM pattern analysis is a future enhancement if/when known patterns prove insufficient.

**If implemented:** LLM outputs must be structured and validated. Never allow LLM to override a rule-based rug risk flag.

---

## Prohibited Uses of LLMs

These are explicit prohibitions. Any code that uses an LLM for the following is in violation of this policy.

### Prohibited: Scoring Decisions

**Never use an LLM to:**
- Compute any dimension score
- Determine an alert type
- Set probability values (P_potential, P_failure, net_potential)
- Override or adjust scores produced by the scoring engine

**Why:** Scores must be auditable and reproducible. LLM outputs are neither. A user asking "why did this get a score of 0.72?" must receive an answer traceable to specific inputs and formulas.

---

### Prohibited: Rug Risk Assessment

**Never use an LLM to:**
- Evaluate whether a token is a rug
- Interpret deployer behavior
- Assess wallet clustering

**Why:** Rug risk assessment must be based on on-chain facts interpreted by rules. An LLM "feeling" that something looks like a rug is not a valid signal and introduces unreliable false positives and false negatives.

---

### Prohibited: OG Resolution

**Never use an LLM to:**
- Determine which token is the OG
- Score authenticity signals

**Why:** OG resolution is based on timing, name precision, and cross-source validation — all computable deterministically. An LLM does not have access to real-time cross-source data; it would be fabricating an assessment.

---

### Prohibited: Primary Narrative Detection

**Never use an LLM to:**
- Decide what narratives are trending
- Score narrative attention strength

**Why:** Narrative detection relies on measuring real-world attention signals from actual sources. An LLM cannot measure what people are currently searching for or reading. It can only know what it was trained on.

---

## LLM Output Validation Rules

When LLM output is used (only in approved cases), it must be validated before entering the system:

1. **Schema validation:** Output must match the expected JSON schema exactly. Invalid schemas reject the output entirely — never partially use malformed LLM responses.

2. **Range validation:** Numeric values must be in expected ranges. A confidence value of 1.5 or -0.3 rejects the call.

3. **Reference validation:** Any IDs returned (e.g., narrative_id) must be verified to exist in the current system state.

4. **Fallback required:** Every LLM call must have a deterministic fallback. If the LLM call fails, times out, or returns invalid output, the fallback runs and the system continues with degraded functionality — it does not halt.

5. **Logging required:** Every LLM call must be logged: input prompt, raw output, validation result, final output after validation. This log must be queryable for debugging.

---

## Prompt Management

All prompts used in LLM calls are:
- Defined as fixed templates (not assembled dynamically from user data)
- Versioned (prompt changes must be documented and logged)
- Tested before deployment (expected outputs for test inputs must be verified)
- Stored in a versioned location in the codebase, not hardcoded inline

When a prompt changes, update the version and document what changed and why.

---

## Cost and Latency Budget

LLM calls are expensive and slow relative to deterministic logic. Current constraints:

- LLM calls are acceptable only in the correlation layer (Layer 4 matching)
- Maximum acceptable latency per LLM call: 5 seconds (with 10-second timeout)
- LLM calls are not on the critical path for `exit-risk` alert generation
- Budget: track cost per LLM call and per day; raise alert if daily LLM cost exceeds threshold

If LLM latency becomes a bottleneck for alert generation, move LLM calls to a background enrichment pipeline rather than the critical scoring path.

---

## The "Would This Benefit From an Agent?" Test

Before adding any LLM/agent component, answer these questions:

1. **Can this be done deterministically?** If yes, do it deterministically.
2. **Does failure of this component block alert generation?** If yes, LLM is too risky; use deterministic logic.
3. **Is the output structured and validatable?** If the LLM output cannot be constrained to a fixed schema, it cannot be used.
4. **Can you write a test that would catch LLM output that is wrong?** If no, you cannot know when it breaks.
5. **Is there a deterministic fallback?** There must be one.

If all five questions have satisfactory answers, an LLM component may be appropriate. If any question fails, do not use an LLM for that task.
