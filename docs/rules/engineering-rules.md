# Engineering Rules

These rules govern how code is written and maintained in this project. They are not preferences. They are enforced constraints.

---

## Rule 1: Documentation Before Code

Before writing any new function, module, or feature, the behavior must be described in a doc. The doc is the specification; the code is the implementation.

If you cannot find a doc describing the behavior you are implementing, either:
- Write the doc first, then write the code
- Find the relevant doc and update it to include the new behavior, then write the code

Code that exists without a corresponding doc entry is technical debt.

**Exception:** Trivial implementation details (helper functions, internal utilities) do not need individual doc entries. But the feature they support must be documented.

---

## Rule 2: No Hardcoded Configuration Values

These values must never be hardcoded in source code:
- API keys or credentials
- Probability weights (from `docs/intelligence/probability-framework.md`)
- Alert classification thresholds (from `docs/alerting/alert-types.md`)
- Rate limits
- Polling intervals
- Risk score thresholds

All configurable values live in configuration files. Code reads configuration at startup or runtime, not at compile time.

**Why:** These values need to change without a code deployment. Weight tuning, threshold adjustments, and rate limit changes are operational, not engineering, tasks.

---

## Rule 3: Fail Loudly, Fail Specifically

When something goes wrong:
- Log the specific error with enough context to diagnose it
- Surface the failure to the appropriate layer (don't catch and swallow exceptions silently)
- Use specific error types, not generic catch-all exceptions
- Include the input that caused the failure in the log (at appropriate truncation)

Do not write code like:
```python
try:
    result = do_thing()
except Exception:
    pass  # silently fails
```

Write code like:
```python
try:
    result = do_thing()
except SpecificError as e:
    logger.error("do_thing failed for token_id=%s: %s", token_id, str(e))
    raise ProcessingError(f"Failed to process token {token_id}") from e
```

---

## Rule 4: Every External Call Has a Timeout

No external API call, database query, or network operation may be written without an explicit timeout. Hanging calls block pipelines and degrade the system.

Default timeouts (configurable):
- External API calls: 10 seconds
- Database queries: 5 seconds
- LLM API calls: 15 seconds (with longer allowed for complex prompts)

---

## Rule 5: Every External Call Has Retry Logic

All external dependencies fail. All of them. Code that calls external services must handle transient failures with retry and backoff.

Pattern:
```
attempt 1 → fail → wait 2s
attempt 2 → fail → wait 4s
attempt 3 → fail → wait 8s
attempt 4 → fail → raise PermanentError
```

Non-retryable errors (4xx client errors, schema validation failures) should not be retried.

---

## Rule 6: Null Is Not Zero, Unknown Is Not False

The system distinguishes between:
- A value that is known to be zero/false/empty
- A value that is unknown (could not be fetched, source unavailable)

`null` means unknown. `0` means zero. `false` means false. These are not interchangeable.

When data is missing, store `null` and record the gap in `data_gaps[]`. Never substitute `0` for unknown volume, `false` for unknown liquidity lock status, or empty string for unavailable description.

---

## Rule 7: All State Transitions Are Logged

When an entity changes status (token status changes, alert type changes, narrative state changes), the transition must be logged:
- Previous state
- New state
- Timestamp
- Reason for transition

State transitions without logged reasons make debugging impossible.

---

## Rule 8: Tests Must Exist for Scoring Logic

The probability framework (formulas and weights) and alert classification thresholds are critical correctness requirements. They must have unit tests that verify:
- Given known inputs, the correct scores are produced
- Classification thresholds produce the correct alert types
- Boundary conditions (exact threshold values) produce the conservative result (round down, not up)
- Missing data (nulls) are handled correctly

These tests must be run before any changes to scoring logic or thresholds are deployed.

---

## Rule 9: Deployment Configuration Is Versioned

Every production deployment must be traceable to:
- The exact code version (git commit)
- The exact configuration values in use

Configuration files are version-controlled. Configuration changes require a commit, not just a file edit.

---

## Rule 10: No Feature Flags for Core Logic

Feature flags are used for UI experiments and gradual rollouts. They are not appropriate for core scoring logic or alert classification.

If you need to change how scoring works, change it. Do not put it behind a flag "until we're sure." If you're not sure, the design needs more thought before implementation.

---

## Rule 11: No Circular Dependencies Between Modules

The dependency hierarchy is:
```
Delivery → Alerting → Scoring → Correlation → Ingestion
```

Higher layers depend on lower layers. Lower layers do not depend on higher layers. A change in the delivery layer must not affect the scoring layer.

---

## Rule 12: Schema Changes Require Versioning

Any change to canonical record schemas (TokenRecord, EventRecord, ChainDataRecord, SocialRecord, ScoredToken, Alert) requires:
1. Incrementing the schema version
2. Updating `docs/implementation/data-model.md`
3. Updating `docs/ingestion/normalization.md` if it's an ingestion schema
4. Ensuring backward-reading code handles both old and new versions during transition

Breaking schema changes without versioning corrupt data and break pipelines silently.
