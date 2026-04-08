"""Layered name matching: exact -> normalized -> abbreviation -> related term.

Reference: docs/intelligence/narrative-linking.md — Matching Approach (Layers 1-3).

Matching is deterministic. No LLM calls are used in these layers.
Layer 4 (semantic/LLM-assisted) is handled separately per docs/implementation/agent-strategy.md.
"""

from __future__ import annotations

from mctrend.config.settings import Settings

# ---------------------------------------------------------------------------
# Load configurable suffix list from settings
# ---------------------------------------------------------------------------

_settings = Settings.load()
STRIP_SUFFIXES: list[str] = _settings.correlation.strip_suffixes


def normalize_name(name: str) -> str:
    """Uppercase, strip whitespace, remove common suffixes.

    Stripping happens only when the remaining stem is longer than 1 character
    to avoid reducing a short token name to nothing.
    """
    clean = name.strip().upper().replace(" ", "").replace("-", "").replace("_", "")
    for suffix in STRIP_SUFFIXES:
        if clean.endswith(suffix) and len(clean) > len(suffix) + 1:
            clean = clean[: -len(suffix)]
    return clean


# ---------------------------------------------------------------------------
# Layer 1 — Exact Match
# ---------------------------------------------------------------------------


def exact_match(token_name: str, anchor_term: str) -> float | None:
    """Layer 1: Direct exact match after normalization. Returns confidence or None.

    Confidence: 0.95 (high end of the 0.85-1.0 band documented for Layer 1).
    """
    if normalize_name(token_name) == normalize_name(anchor_term):
        return 0.95
    # Also try raw uppercase comparison (catches cases where suffix stripping
    # would incorrectly alter one side but not the other).
    if token_name.strip().upper() == anchor_term.strip().upper():
        return 0.95
    return None


# ---------------------------------------------------------------------------
# Layer 2 — Abbreviation / Prefix / Near-Match
# ---------------------------------------------------------------------------


def abbreviation_match(token_name: str, anchor_term: str) -> float | None:
    """Layer 2: Abbreviation, prefix, truncation, and Levenshtein matching.

    Confidence range: 0.55-0.84 per docs/intelligence/narrative-linking.md.
    """
    tn = normalize_name(token_name)
    at = normalize_name(anchor_term)

    if not tn or not at:
        return None

    # Token is first N chars of anchor (min 3 chars for meaningful prefix)
    if len(tn) >= 3 and at.startswith(tn):
        # Longer prefix match -> higher confidence (0.55 base + up to 0.15 bonus)
        return 0.55 + 0.15 * (len(tn) / len(at))

    # Token is first-letter abbreviation of multi-word anchor
    words = anchor_term.strip().upper().split()
    if len(words) >= 2:
        initials = "".join(w[0] for w in words if w)
        if tn == initials and len(initials) >= 2:
            return 0.60

    # Levenshtein distance <= 2 for similar-length strings (min 4 chars)
    if abs(len(tn) - len(at)) <= 2 and len(tn) >= 4:
        dist = _levenshtein(tn, at)
        if dist <= 2:
            return max(0.55, 0.80 - dist * 0.12)

    return None


# ---------------------------------------------------------------------------
# Layer 3 — Related Term Match
# ---------------------------------------------------------------------------


def related_term_match(
    token_name: str, related_terms: list[str]
) -> tuple[float, str] | None:
    """Layer 3: Match against narrative's related terms list.

    Confidence range: 0.35-0.54 per docs/intelligence/narrative-linking.md.
    Returns (confidence, matched_term) or None.
    """
    tn = normalize_name(token_name)

    if not tn:
        return None

    for term in related_terms:
        normalized_term = normalize_name(term)
        if not normalized_term:
            continue
        # Exact match against a related term
        if tn == normalized_term:
            return 0.45, term
        # Prefix match (either direction) with minimum 3 chars
        if len(tn) >= 3 and (
            normalized_term.startswith(tn) or tn.startswith(normalized_term)
        ):
            return 0.35, term

    return None


# ---------------------------------------------------------------------------
# Composite matcher
# ---------------------------------------------------------------------------


def match_token_to_narrative(
    token_name: str,
    token_symbol: str,
    anchor_terms: list[str],
    related_terms: list[str],
) -> dict:
    """Run all matching layers and return best match result.

    Both *token_name* and *token_symbol* are tested against every anchor term
    (Layers 1 & 2) and every related term (Layer 3).  The highest-confidence
    match across all combinations is returned.

    Returns::

        {
            "matched": bool,
            "confidence": float,
            "method": str,       # "exact" | "abbreviation" | "related_term" | "none"
            "matched_term": str | None,
            "signals": list[str],
        }
    """
    best_confidence: float = 0.0
    best_method: str = "none"
    best_term: str | None = None
    signals: list[str] = []

    # Candidate token strings to test (name and symbol may differ)
    candidates = [token_name, token_symbol]

    # --- Layers 1 & 2 against anchor terms ---
    for candidate in candidates:
        if not candidate:
            continue
        for anchor in anchor_terms:
            # Layer 1: exact
            conf = exact_match(candidate, anchor)
            if conf is not None and conf > best_confidence:
                best_confidence = conf
                best_method = "exact"
                best_term = anchor

            # Layer 2: abbreviation / near-match
            conf = abbreviation_match(candidate, anchor)
            if conf is not None and conf > best_confidence:
                best_confidence = conf
                best_method = "abbreviation"
                best_term = anchor

    # --- Layer 3 against related terms ---
    for candidate in candidates:
        if not candidate:
            continue
        result = related_term_match(candidate, related_terms)
        if result is not None:
            conf, term = result
            if conf > best_confidence:
                best_confidence = conf
                best_method = "related_term"
                best_term = term

    # --- Build signals list ---
    matched = best_confidence > 0.0 and best_method != "none"

    if best_method == "exact":
        signals.append("exact_anchor_match")
    elif best_method == "abbreviation":
        signals.append("abbreviation_match")
    elif best_method == "related_term":
        signals.append("related_term_match")

    # Check if both name and symbol independently produce matches (stronger signal)
    if matched and token_name and token_symbol:
        name_has_match = False
        symbol_has_match = False
        for anchor in anchor_terms:
            if exact_match(token_name, anchor) is not None:
                name_has_match = True
            if exact_match(token_symbol, anchor) is not None:
                symbol_has_match = True
        if name_has_match and symbol_has_match:
            signals.append("name_and_symbol_both_match")

    return {
        "matched": matched,
        "confidence": best_confidence,
        "method": best_method,
        "matched_term": best_term,
        "signals": signals,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _levenshtein(s1: str, s2: str) -> int:
    """Standard dynamic-programming Levenshtein distance."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = list(range(len(s2) + 1))

    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            # insertion, deletion, substitution
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (0 if c1 == c2 else 1)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]
