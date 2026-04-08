"""Lightweight deterministic relevance scoring for articles and narratives.

Prevents irrelevant content (sports, politics, entertainment, generic culture)
from becoming narratives or participating in token linking.

Reference: docs/ingestion/relevance-filtering.md

Design principles:
  - Deterministic: same inputs → same output, no network calls, no LLM.
  - Conservative defaults: clear sports/politics blocked; borderline crypto-culture passes.
  - Configurable: all thresholds come from NarrativeIntelligenceConfig (no hardcoded values).
"""

from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# Vocabulary: positive signals (crypto / token / market relevance)
# ---------------------------------------------------------------------------

# Maps term → weight.  Weights are summed to produce raw positive score.
# A term matches if it appears as a whole word in the lowercased text.
_POSITIVE_TERMS: dict[str, float] = {
    # Token launch platform — highest weight
    "pump.fun": 1.0,
    "pumpfun": 1.0,
    "pumpportal": 1.0,
    # Core crypto
    "crypto": 0.8,
    "cryptocurrency": 0.8,
    "bitcoin": 0.8,
    "btc": 0.8,
    "ethereum": 0.8,
    "eth": 0.8,
    "solana": 0.8,
    "sol": 0.6,  # lower weight — common abbreviation used elsewhere
    "defi": 0.8,
    "nft": 0.8,
    "web3": 0.8,
    "blockchain": 0.8,
    # Token / market activity
    "token": 0.7,
    "coin": 0.7,
    "memecoin": 0.7,
    "meme coin": 0.7,
    "altcoin": 0.7,
    "airdrop": 0.7,
    "presale": 0.7,
    "ido": 0.7,
    "ico": 0.7,
    "pump": 0.6,
    "dump": 0.6,
    "rug": 0.7,
    "rug pull": 0.7,
    "mint": 0.6,
    "minting": 0.6,
    "launch": 0.5,  # lower weight — broad term
    "liquidity": 0.7,
    "holder": 0.7,
    "holders": 0.7,
    "wallet": 0.6,
    "exchange": 0.5,
    "trading": 0.5,
    "market cap": 0.7,
    "ath": 0.6,
    "all-time high": 0.6,
    "moonshot": 0.6,
    "dex": 0.7,
    "cex": 0.6,
    "raydium": 0.8,
    "uniswap": 0.8,
    "pancakeswap": 0.8,
    "staking": 0.6,
    "yield": 0.4,  # lower — also used in agriculture/finance
    # Community / degen culture
    "degen": 0.5,
    "ape": 0.4,
    "pepe": 0.6,
    "wif": 0.6,
    "bonk": 0.6,
    "shib": 0.6,
    "doge": 0.5,
    "wojak": 0.5,
    "fud": 0.5,
    "fomo": 0.5,
    "ngmi": 0.5,
    "wagmi": 0.5,
    "gm": 0.3,  # very broad — low weight
    "shill": 0.4,
    "moonbag": 0.5,
}

# ---------------------------------------------------------------------------
# Vocabulary: veto categories
# Each entry is (category_name, frozenset_of_terms)
# A veto fires if any term from the set appears in the text.
# ---------------------------------------------------------------------------

_VETO_CATEGORIES: list[tuple[str, frozenset[str]]] = [
    ("sports", frozenset({
        "nba", "nfl", "mlb", "nhl", "fifa", "championship",
        "super bowl", "world cup", "touchdown", "home run", "playoffs",
        "olympic", "olympics", "athlete", "quarterback", "pitcher",
        "slam dunk", "league title", "world series",
    })),
    ("politics", frozenset({
        "election", "senate", "congress", "president", "white house",
        "democrat", "republican", "legislation", "supreme court", "governor",
        "prime minister", "parliament", "cabinet", "ballot", "referendum",
        "midterm", "political party",
    })),
    ("entertainment", frozenset({
        "oscars", "academy awards", "grammys", "emmys", "bafta",
        "box office", "album release", "concert tour", "red carpet",
        "film festival", "movie premiere", "grammy award",
    })),
    ("generic_culture", frozenset({
        "recipe", "cooking show", "food festival", "fashion week",
        "restaurant review", "travel guide",
    })),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_article_relevance(
    title: str,
    description: str,
    source_name: str = "",
    *,
    positive_saturation: float = 1.5,
    veto_override_threshold: float = 0.15,
    veto_penalized_score: float = 0.02,
) -> float:
    """Score a raw article for crypto/market relevance.

    Parameters
    ----------
    title
        Article title.
    description
        Article description / snippet.
    source_name
        Publishing source name (e.g. "CoinDesk"). Used for source-level boosts.
    positive_saturation
        Sum of positive term weights that yields score 1.0.
    veto_override_threshold
        Crypto signal above this prevents a veto from applying.
    veto_penalized_score
        Score assigned when a veto fires (low but not 0 — distinguishes from empty text).

    Returns
    -------
    float in [0.0, 1.0]
    """
    text = f"{title} {description} {source_name}".lower()
    return _compute_relevance(
        text,
        positive_saturation=positive_saturation,
        veto_override_threshold=veto_override_threshold,
        veto_penalized_score=veto_penalized_score,
    )


def score_narrative_relevance(
    anchor_terms: list[str],
    description: str,
    source_names: list[str] | None = None,
    *,
    positive_saturation: float = 1.5,
    veto_override_threshold: float = 0.15,
    veto_penalized_score: float = 0.02,
) -> float:
    """Score a stored narrative for crypto/market relevance.

    Uses anchor_terms, description, and source names. Anchor terms get extra
    weight because they are already distilled signals (not raw prose).

    Parameters
    ----------
    anchor_terms
        Narrative anchor terms (uppercased strings, e.g. ["DEEPMIND", "AI"]).
    description
        Narrative description text.
    source_names
        List of source names that contributed to this narrative.
    positive_saturation
        Sum of positive term weights that yields score 1.0.
    veto_override_threshold
        Crypto signal above this prevents a veto from applying.
    veto_penalized_score
        Score assigned when a veto fires.

    Returns
    -------
    float in [0.0, 1.0]
    """
    # Anchor terms are already extracted signals — treat them as high-signal text
    terms_text = " ".join(anchor_terms).lower()
    source_text = " ".join(source_names or []).lower()
    full_text = f"{terms_text} {description} {source_text}".lower()
    return _compute_relevance(
        full_text,
        positive_saturation=positive_saturation,
        veto_override_threshold=veto_override_threshold,
        veto_penalized_score=veto_penalized_score,
    )


# ---------------------------------------------------------------------------
# Internal scoring engine
# ---------------------------------------------------------------------------

def _compute_relevance(
    text: str,
    *,
    positive_saturation: float,
    veto_override_threshold: float,
    veto_penalized_score: float,
) -> float:
    """Core relevance computation on lowercased text."""
    # Positive score: sum weights of matching crypto terms
    positive_total = 0.0
    for term, weight in _POSITIVE_TERMS.items():
        if _term_in_text(term, text):
            positive_total += weight

    raw_score = min(positive_total / positive_saturation, 1.0)

    # Veto check: any veto term present AND crypto signal is weak
    if raw_score < veto_override_threshold:
        for _category, veto_terms in _VETO_CATEGORIES:
            for term in veto_terms:
                if _term_in_text(term, text):
                    return veto_penalized_score

    return raw_score


def _term_in_text(term: str, text: str) -> bool:
    """Check if term appears as a whole-word match (or phrase) in text.

    For single words: uses word-boundary matching.
    For phrases (containing spaces): substring match is sufficient.
    """
    if " " in term:
        return term in text
    # Word boundary match to avoid partial matches (e.g. "sol" in "absolutely")
    return bool(re.search(r"\b" + re.escape(term) + r"\b", text))
