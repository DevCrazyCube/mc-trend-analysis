# Narrative Linking

This document defines how tokens are matched to real-world narratives and how the quality of that match is scored.

---

## What Is a Narrative

A "narrative" is a real-world event, trend, cultural moment, or topic that is generating measurable attention outside the crypto ecosystem.

Examples:
- A major AI company releases a product
- A celebrity makes a viral statement
- A political event produces a meme
- A sports event creates a cultural moment
- A news story about a specific animal, technology, or phenomenon goes viral

Narratives have:
- **Anchor terms**: specific words or names central to the narrative
- **Related terms**: adjacent concepts that may appear in token names
- **Source signals**: which platforms are showing attention for this narrative
- **Lifecycle state**: emerging, peaking, declining, dead
- **Strength**: how much attention is being generated

---

## The Matching Problem

Token names are short, often creative, sometimes ambiguous. Narrative matching is not a simple keyword lookup.

Challenges:
- Token `$GEMINI` during a Google AI news cycle vs. during an astrology trend — same name, different narrative
- Token `$HAWK` could match a bird trend, a military technology story, or a politician's name
- Tokens intentionally use abbreviations, misspellings, or variations: `$DEEPMIND` vs. `$DMIND` vs. `$DEEP`
- Multiple active narratives may share similar terms
- Token names are often set by deployers who are themselves trend-matching — they're solving the same problem

---

## Matching Approach

Matching is done in layers, from most deterministic to least:

### Layer 1: Exact Term Match

Direct match between token name or symbol and a known narrative anchor term.

Examples:
- Token `$DEEPMIND`, narrative anchor: "deepmind" → exact match
- Token `$DOGE`, narrative anchor: "doge" → exact match

**Confidence contribution:** High (0.85–1.0 base)

---

### Layer 2: Near-Exact and Abbreviation Match

Known transformations of anchor terms: abbreviations, prefixes, suffixes, common crypto-name patterns.

Examples:
- `$DMIND` → abbreviation of "deepmind" → near-exact match
- `$DOGECOIN2` → `doge` + `coin` suffix → near-exact match
- `$SUPERSOL` → `sol` suffix, would only match Solana-specific narratives, not standalone

**Confidence contribution:** Medium-High (0.55–0.84)

---

### Layer 3: Related Term Match

Token contains a term closely related to the narrative but not the anchor term itself.

Examples:
- Token `$GEMINI` during a Google AI story (Gemini is a Google AI product)
- Token `$GOAT` during a sports GOAT debate narrative

**Confidence contribution:** Medium (0.35–0.54)

Requires validation: does this term appear in the narrative source material, or is this a stretch?

---

### Layer 4: Semantic / LLM-Assisted Match

When layers 1–3 produce no confident match but a human would clearly see the connection.

Examples:
- Token `$GALAXY` launched during a NASA announcement about a galaxy discovery
- Token `$BOXER` launched during a viral boxing match

**When to use:** Only when deterministic layers fail and the token has other activity signals worth pursuing.

**Confidence contribution:** Low-Medium (0.15–0.40)

**Constraints on LLM use here:**
- LLM must return a structured response: match_found (bool), narrative_id (if found), rationale (string), confidence (float)
- LLM output is not trusted blindly: confidence above 0.5 requires at least one deterministic corroborating signal
- LLM reasoning must be stored and logged for auditability
- If LLM and deterministic methods disagree on confidence by > 0.3, flag for review

---

### Layer 5: No Match

Token does not match any active narrative above minimum confidence threshold (0.15).

Token is marked `unlinked`. No scoring occurs. No alert generated.

---

## Narrative Match Quality Signals

Each match record includes a `match_signals[]` array that explains which factors contributed:

| Signal | Description |
|---|---|
| `exact_anchor_match` | Token name matches anchor term exactly |
| `abbreviation_match` | Token is known abbreviation of anchor term |
| `related_term_match` | Token contains narrative-related term |
| `semantic_match` | LLM-assisted match |
| `narrative_age_fresh` | Narrative is < 2 hours old at time of match |
| `narrative_age_decaying` | Narrative is > 6 hours old, likely past peak |
| `multi_source_narrative` | Narrative confirmed by 3+ independent source types |
| `single_source_narrative` | Narrative only from one source type |
| `narrative_velocity_positive` | Attention on narrative is growing |
| `narrative_velocity_negative` | Attention on narrative is declining |

---

## Narrative Lifecycle and Decay

Narratives are not static. They have a lifecycle:

```
EMERGING → PEAKING → DECLINING → DEAD
```

The system tracks narrative state by monitoring attention signals across sources.

**Lifecycle thresholds (approximate, subject to calibration):**

| State | Definition |
|---|---|
| EMERGING | First detected within last 2 hours; attention velocity positive |
| PEAKING | Attention magnitude at or near maximum; velocity slowing or flat |
| DECLINING | Attention falling more than 20% from peak |
| DEAD | Attention below minimum threshold across all sources |

**Implication for scoring:**
- EMERGING: high timing quality score
- PEAKING: medium timing quality score
- DECLINING: low timing quality score
- DEAD: token linked to this narrative marked for re-evaluation; narrative link may be retired

---

## Ambiguity Handling

When a token name could plausibly match multiple active narratives, create links to all candidates with confidence scores reflecting the ambiguity:

Example: Token `$HAWK` during both a military news cycle and a bird-goes-viral story.
- Link to military narrative: confidence 0.42
- Link to bird narrative: confidence 0.51

Both links are retained. Both are scored. The higher-confidence narrative drives the primary alert, but both are logged.

If the confidence gap is < 0.15, flag the token as `narrative_ambiguous` and reduce the overall `confidence_score` for any alert.

---

## Cross-Source Validation

A narrative match gains confidence when independent sources agree:

| Evidence | Confidence Boost |
|---|---|
| Narrative term appears in search trends AND crypto news | +0.10 |
| Narrative term appears in search trends AND mainstream news | +0.15 |
| This specific token is mentioned (not just the narrative) in 2+ independent sources | +0.20 |
| Narrative has been active for > 30 minutes across sources (not a spike) | +0.10 |

These boosts are applied to the base match confidence before it feeds into the narrative relevance dimension score.

---

## What Narrative Linking Is Not

- It is not a prediction that this narrative will sustain
- It is not a claim that the token is legitimate
- It is not a confirmation that the token launched because of the narrative (the deployer may have purely coincidentally used the name)

Narrative linking is a signal, not a fact. The score reflects how well the available evidence supports the connection.
