# Entity Resolution

This document defines patterns for matching tokens to narratives and for identifying when multiple records refer to the same real-world entity.

---

## What Is Entity Resolution

Entity resolution is the process of determining that:
- Two different records refer to the same underlying entity (deduplication)
- A record refers to a specific known entity (linking)

In this system, entity resolution covers:
1. Matching token names to narrative anchor terms
2. Determining which of multiple tokens belongs to the same namespace
3. Matching news articles and social posts about the same underlying event

---

## Resolution Layer Architecture

Resolution is done in ordered layers, from most reliable to least. Stop at the first layer that produces confident results.

```
Layer 1: Exact Match
Layer 2: Normalized Exact Match
Layer 3: Abbreviation and Pattern Match
Layer 4: Related Term Match
Layer 5: Semantic Match (LLM-assisted)
Layer 6: No Match
```

### Layer 1: Exact Match

**Process:** Compare token name/symbol directly to anchor terms in active narratives.

**Normalization:** Convert both sides to uppercase. Strip common token suffixes (`COIN`, `TOKEN`, `INU`, `2`, `V2`).

**Examples:**
- Token `$DEEPMIND` vs. narrative anchor `DEEPMIND` → match
- Token `$DEEPMINDCOIN` vs. anchor `DEEPMIND` → match (after stripping `COIN` suffix)

**Confidence:** 0.90–1.0

**Implementation:**
```python
def exact_match(token_name: str, anchor: str) -> float | None:
    clean_token = strip_suffixes(token_name.upper())
    clean_anchor = anchor.upper()
    if clean_token == clean_anchor:
        return 0.95
    return None

STRIP_SUFFIXES = ["COIN", "TOKEN", "INU", "2", "V2", "FI", "AI", "SOL"]

def strip_suffixes(name: str) -> str:
    for suffix in STRIP_SUFFIXES:
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[:-len(suffix)]
    return name
```

---

### Layer 2: Normalized Exact Match

**Process:** Apply additional normalizations and retry exact match.

Normalizations:
- Remove spaces, hyphens, underscores
- Expand known abbreviations (e.g., `BTC` → `BITCOIN`)
- Try common variations (e.g., `ELON` → `ELONMUSK`, and reverse)

**Confidence:** 0.75–0.89

---

### Layer 3: Abbreviation and Pattern Match

**Process:** Check if the token name is a known pattern derived from the anchor term.

Known patterns:
- First letters of words: `AI` from `Artificial Intelligence`
- First N characters: `DEEP` from `DEEPMIND`
- Common crypto naming suffixes added to base: `DOGGI` (from `DOGE`)
- Phonetic variants: `BTTCOIN` → `BITCOIN` (Levenshtein distance ≤ 2)

**Confidence:** 0.55–0.74

**Caution:** Abbreviation matching produces false positives. `BTC` is an abbreviation of many things. Apply a minimum token-anchor specificity check: the anchor must be at least 5 characters or the token must have additional evidence.

---

### Layer 4: Related Term Match

**Process:** The token name is not the anchor term itself but is closely related to the narrative.

**Implementation:** Check if the token name appears in the narrative's `related_terms` list, or if it is a known synonym for an anchor term.

Example: Narrative anchor `DEEPMIND` → related terms include `AI`, `GEMINI`, `GOOGLE AI`. Token `$GEMINI` matches via related terms.

**Confidence:** 0.35–0.54

---

### Layer 5: Semantic Match (LLM-Assisted)

**Process:** All deterministic layers failed. Use an LLM to assess whether the token name plausibly relates to any active narrative.

**When triggered:** Only when the token has other signals suggesting it might be narratively relevant (e.g., unusual trading activity, social mentions appearing alongside narrative terms).

**Constraints:** See `docs/implementation/agent-strategy.md`. LLM output is validated and capped at confidence 0.40 maximum.

---

### Layer 6: No Match

If all layers fail, the token is marked `unlinked`. No further scoring occurs.

---

## Narrative Deduplication

When multiple news articles or social posts reference the same underlying event, they should produce one `EventRecord`, not many.

**Grouping key algorithm:**

1. Extract anchor terms from each incoming signal
2. Compute Jaccard similarity of anchor term sets: `|A ∩ B| / |A ∪ B|`
3. If similarity > 0.50 AND signals are within 2 hours of each other → same event
4. If similarity > 0.30 AND one signal is clearly a follow-up to the other → same event

**Anti-pattern:** Don't be too aggressive with grouping. A story about "Google" and a story about "Deepmind" may be different events even if they share some entity overlap.

---

## Token Namespace Resolution

A "namespace" is the set of all tokens that match the same narrative with confidence > 0.30.

When a namespace has more than one member:
1. Sort by OG score (from `docs/intelligence/og-token-resolution.md`)
2. Mark all members with their `og_rank`
3. All members remain in the scoring pipeline — no suppression

**Namespace collision detection:**
- Two namespaces that share anchor terms are flagged as `namespace_collision`
- Tokens matched to a colliding namespace receive `NARRATIVE_AMBIGUOUS` risk flag
- Both namespaces remain active

---

## Cross-Source Token Mention Matching

**Problem:** A news article mentions a specific token by name. We need to match this mention to an existing token in the registry.

**Process:**
1. Extract token names from the article using entity recognition
2. Normalize extracted names
3. Look up in token registry by normalized name
4. If ambiguous (multiple tokens with same normalized name): match by chain context and recency
5. If match found: update the token's `cross_source_mentions` count and the OG resolver

**Confidence threshold for cross-source mention:** Only count a mention if the extracted token name matches exactly (Layer 1) or via Layer 2. Do not count ambiguous mentions as confirmed cross-source references.

---

## Handling Namespace Poisoning

**Namespace poisoning:** A bad actor deliberately deploys a token with a name identical to an existing token to steal its narrative association or confuse the OG resolver.

**Detection:**
- Two tokens with identical normalized names
- One of them launched significantly later (minutes to hours)
- The later one may have different deployer patterns

**Handling:**
- Both tokens go through OG resolution normally
- The later-deployer duplicate receives additional `NAMESPACE_CONFLICT` flag
- OG resolver's temporal priority signal heavily penalizes the later duplicate
- Both remain in the scoring pipeline — the OG resolver's output is the primary differentiation
