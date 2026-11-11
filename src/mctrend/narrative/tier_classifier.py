"""Narrative tier classification — deterministic signal hierarchy.

Every narrative candidate is assigned a signal tier based on its evidence mix,
semantic gravity (topic category relevance), and noise characteristics.

Tiers
-----
TIER_1 — External Reality / High-Gravity Narrative
    Political events, regulation, geopolitics, major companies/figures.
    Often appears in news, may cause token creation downstream.

TIER_2 — Large Social Momentum / Internet Attention
    Viral meme phrases with real spread, major influencer discourse,
    strong repeated theme on X from many independent accounts.

TIER_3 — Token-Echo Narrative
    Phrase appears across multiple token names with no external corroboration.
    Lowest trust by default; only useful when explosive and persistent.

TIER_4 — Noise / Trash
    Low-meaning token names, copycat spam, boilerplate, generic crypto filler.
    Should not surface as narratives; debug only.

All logic is deterministic and auditable.  No LLM, no randomness.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Tier labels
# ---------------------------------------------------------------------------

TIER_1 = "T1"
TIER_2 = "T2"
TIER_3 = "T3"
TIER_4 = "T4"

TIER_WEIGHT = {TIER_1: 4, TIER_2: 3, TIER_3: 2, TIER_4: 1}

TIER_LABEL = {
    TIER_1: "External Reality",
    TIER_2: "Social Momentum",
    TIER_3: "Token Echo",
    TIER_4: "Noise",
}


# ---------------------------------------------------------------------------
# Semantic gravity categories — keyword sets for real-world topic detection
# ---------------------------------------------------------------------------

_POLITICS: frozenset[str] = frozenset({
    "TRUMP", "BIDEN", "OBAMA", "ELECTION", "VOTE", "CONGRESS", "SENATE",
    "PRESIDENT", "WHITEHOUSE", "DEMOCRAT", "REPUBLICAN", "GOP", "MAGA",
    "POTUS", "CAMPAIGN", "IMPEACH", "DEBATE", "INAUGURATION",
    "KAMALA", "HARRIS", "DESANTIS", "VIVEK", "RFKJR", "PENCE",
})

_REGULATION: frozenset[str] = frozenset({
    "SEC", "ETF", "REGULATION", "LAWSUIT", "LEGAL", "COMPLIANCE",
    "BAN", "SANCTION", "FINE", "APPROVAL", "RULING", "COURT",
    "GENSLER", "CFTC", "DOJ", "TREASURY", "FED", "FOMC",
    "TARIFF", "TRADE", "INTEREST", "RATE", "INFLATION",
})

_GEOPOLITICS: frozenset[str] = frozenset({
    "WAR", "CONFLICT", "INVASION", "NATO", "UKRAINE", "RUSSIA",
    "CHINA", "TAIWAN", "IRAN", "ISRAEL", "GAZA", "PALESTINE",
    "MISSILE", "SANCTION", "CEASEFIRE", "PEACE", "NUCLEAR",
    "MILITARY", "TROOPS", "ATTACK", "BOMB",
})

_MAJOR_FIGURES: frozenset[str] = frozenset({
    "ELON", "MUSK", "ZUCKERBERG", "BEZOS", "GATES", "BUFFETT",
    "SAYLOR", "CZ", "SBF", "VITALIK", "SATOSHI", "NAKAMOTO",
    "DORSEY", "COOK", "ALTMAN", "SAMA", "MILEI", "BUKELE",
    "KANYE", "DRAKE", "ROGAN", "TATE", "TUCKER", "ALEXJONES",
})

_MAJOR_COMPANIES: frozenset[str] = frozenset({
    "APPLE", "GOOGLE", "MICROSOFT", "TESLA", "NVIDIA", "META",
    "AMAZON", "OPENAI", "COINBASE", "BINANCE", "BLACKROCK",
    "JPMORGAN", "FIDELITY", "GRAYSCALE", "MICROSTRATEGY",
    "ROBINHOOD", "PAYPAL", "VISA", "MASTERCARD", "SPACEX",
})

_CRYPTO_EVENTS: frozenset[str] = frozenset({
    "HACK", "EXPLOIT", "VULNERABILITY", "AUDIT", "BRIDGE",
    "HALVING", "MERGE", "AIRDROP", "SNAPSHOT", "UPGRADE",
    "MAINNET", "TESTNET", "FORK", "RUGPULL", "SCAM",
    "BANKRUPTCY", "INSOLVENCY", "COLLAPSE", "SHUTDOWN",
})

# Category → weight (higher = more semantic gravity)
SEMANTIC_CATEGORIES: dict[str, tuple[frozenset[str], float]] = {
    "politics":        (_POLITICS, 1.0),
    "regulation":      (_REGULATION, 1.0),
    "geopolitics":     (_GEOPOLITICS, 0.9),
    "major_figures":   (_MAJOR_FIGURES, 0.8),
    "major_companies": (_MAJOR_COMPANIES, 0.7),
    "crypto_events":   (_CRYPTO_EVENTS, 0.6),
}


# ---------------------------------------------------------------------------
# Spam / noise detection — phrases and patterns that are always trash
# ---------------------------------------------------------------------------

SPAM_PHRASES: frozenset[str] = frozenset({
    # Generic launch boilerplate
    "MY FIRST COIN", "MY FIRST TOKEN", "FIRST COIN EVER",
    "MY FIRST EVER COIN", "FIRST EVER COIN", "FIRST TOKEN",
    "TO THE MOON", "MOON MISSION", "GOING TO THE MOON",
    "NEXT 100X", "NEXT 1000X", "100X GEM", "1000X GEM",
    "JOIN THE REVOLUTION", "DONT MISS OUT", "STILL EARLY",
    "THE NEXT BIG THING", "NEXT BIG THING", "NEXT SOLANA",
    "THE WORLD IF WE ALL HELD", "WORLD IF WE ALL HELD",
    "BUY NOW", "SEND IT", "APE IN", "FULL SEND",
    "GENERATIONAL WEALTH", "LIFE CHANGING", "QUIT YOUR JOB",
    # Sexually explicit bait
    "SEXY", "BOOBS", "ONLYFANS", "NSFW", "PORN",
    # Pure filler
    "TEST", "TESTING", "HELLO WORLD", "SAMPLE TOKEN",
    "NEW TOKEN", "TOKEN LAUNCH", "JUST LAUNCHED",
    "FAIR LAUNCH", "STEALTH LAUNCH", "NO PRESALE",
})

# Pattern families for phrases that are noise regardless of suffix
SPAM_PATTERN_PREFIXES: tuple[str, ...] = (
    "MY FIRST",
    "THE NEXT",
    "NEXT 10",
    "NEXT 100",
    "100X",
    "1000X",
    "SEND IT",
    "BUY THE",
    "APE THE",
    "INU OF",
    "KING OF",
    "LORD OF",
    "GOD OF",
    "BABY ",
)

# Stopwords — if a phrase is ONLY stopwords, it's noise
_STOPWORDS: frozenset[str] = frozenset({
    "THE", "A", "AN", "OF", "TO", "IN", "FOR", "ON", "AT", "IS",
    "IT", "BY", "MY", "IF", "OR", "AND", "BUT", "NOT", "NO", "WE",
    "BE", "DO", "SO", "UP", "ALL", "ONE", "TWO", "NEW", "OLD",
})


# ---------------------------------------------------------------------------
# Semantic gravity scoring
# ---------------------------------------------------------------------------

def compute_semantic_gravity(term: str) -> tuple[float, list[str]]:
    """Score how strongly a term maps to real-world event categories.

    Returns (score 0.0–1.0, list of matched category names).
    """
    upper = term.upper().strip()
    matched: list[str] = []
    max_weight = 0.0

    for cat_name, (keywords, weight) in SEMANTIC_CATEGORIES.items():
        if upper in keywords:
            matched.append(cat_name)
            max_weight = max(max_weight, weight)
        else:
            # Check if any keyword is a substring of the term (for compound terms)
            for kw in keywords:
                if kw in upper and len(kw) >= 4:
                    matched.append(cat_name)
                    # Substring match gets a smaller weight
                    max_weight = max(max_weight, weight * 0.6)
                    break

    return (max_weight, matched)


# ---------------------------------------------------------------------------
# Noise / spam detection
# ---------------------------------------------------------------------------

def is_spam_phrase(term: str) -> bool:
    """Check if a canonical term matches known spam patterns."""
    upper = term.upper().strip()

    # Exact match
    if upper in SPAM_PHRASES:
        return True

    # Prefix patterns
    for prefix in SPAM_PATTERN_PREFIXES:
        if upper.startswith(prefix):
            return True

    return False


def compute_phrase_entropy(term: str) -> float:
    """Estimate lexical information content of a phrase.

    Low entropy = generic / low-information = likely noise.
    High entropy = specific / distinctive = likely signal.

    Returns a score 0.0–1.0 where higher = more informative.
    """
    words = term.upper().split()
    if not words:
        return 0.0

    # All stopwords → very low entropy
    non_stop = [w for w in words if w not in _STOPWORDS and len(w) > 1]
    if not non_stop:
        return 0.05

    # Single very short word → low
    if len(non_stop) == 1 and len(non_stop[0]) <= 3:
        return 0.2

    # Character-level entropy approximation
    text = "".join(non_stop)
    if len(text) < 3:
        return 0.15

    from collections import Counter
    counts = Counter(text)
    total = len(text)
    entropy = -sum((c / total) * math.log2(c / total) for c in counts.values())

    # Normalize: max entropy for English text is ~4.5 bits/char
    normalized = min(1.0, entropy / 4.5)

    # Bonus for longer distinctive phrases
    length_bonus = min(0.2, len(non_stop) * 0.05)

    return min(1.0, normalized + length_bonus)


def compute_anti_spam_score(
    term: str,
    token_names: list[str],
    x_corroboration: float = 0.0,
    news_corroboration: float = 0.0,
) -> float:
    """Score how likely this narrative is NOT spam. Higher = cleaner.

    Penalizes:
    - Known spam phrases
    - Low entropy / generic phrases
    - Token names that are near-duplicates without external corroboration
    - Very short terms

    Returns 0.0 (definitely spam) to 1.0 (definitely not spam).
    """
    score = 1.0

    # Known spam → immediate floor
    if is_spam_phrase(term):
        return 0.05

    # Entropy penalty
    entropy = compute_phrase_entropy(term)
    if entropy < 0.3:
        score -= 0.4  # heavy penalty for low-information phrases

    # Very short term (1-2 chars) → not meaningful on its own
    if len(term.strip()) <= 2:
        score -= 0.3

    # Token name homogeneity: if all token names look the same, suspicious
    if len(token_names) >= 3:
        from mctrend.narrative.entity_extraction import trigram_jaccard
        avg_sim = 0.0
        pair_count = 0
        names_sample = token_names[:10]
        for i in range(len(names_sample)):
            for j in range(i + 1, len(names_sample)):
                avg_sim += trigram_jaccard(names_sample[i], names_sample[j])
                pair_count += 1
        if pair_count > 0:
            avg_sim /= pair_count
            if avg_sim > 0.85 and x_corroboration == 0.0 and news_corroboration == 0.0:
                score -= 0.25  # all names near-identical, no external corroboration

    # External corroboration partially redeems spam signals
    if x_corroboration > 0:
        score += 0.1
    if news_corroboration > 0:
        score += 0.15

    return max(0.0, min(1.0, score))


# ---------------------------------------------------------------------------
# NarrativeEvidence — input to the tier classifier
# ---------------------------------------------------------------------------

@dataclass
class NarrativeEvidence:
    """All evidence available about a narrative candidate for tier classification."""

    canonical_name: str
    token_count: int = 0
    token_names: list[str] = field(default_factory=list)

    # X evidence
    has_x_corroboration: bool = False
    x_spike_corroboration: float = 0.0
    x_author_count: int = 0
    x_total_engagement: int = 0
    x_post_count: int = 0

    # News evidence
    has_news_corroboration: bool = False
    news_corroboration: float = 0.0
    news_article_count: int = 0
    news_domain_count: int = 0

    # Source mix
    source_types: set[str] = field(default_factory=set)

    # Velocity
    velocity_tokens_5m: int = 0
    velocity_tokens_15m: int = 0
    acceleration: str = "flat"


# ---------------------------------------------------------------------------
# X evidence quality thresholds
# ---------------------------------------------------------------------------

# Minimum thresholds for social-only narrative to be TIER_2
X_MIN_AUTHORS_FOR_T2 = 3           # at least 3 unique authors
X_MIN_ENGAGEMENT_FOR_T2 = 50       # total engagement across all posts
X_MIN_POSTS_FOR_T2 = 3             # at least 3 independent posts

# Thresholds for strong social signal
X_STRONG_AUTHORS = 10
X_STRONG_ENGAGEMENT = 500
X_STRONG_POSTS = 10


# ---------------------------------------------------------------------------
# Tier classification
# ---------------------------------------------------------------------------

def classify_tier(evidence: NarrativeEvidence) -> tuple[str, str, list[str]]:
    """Assign a signal tier to a narrative candidate.

    Parameters
    ----------
    evidence
        All available evidence about the narrative.

    Returns
    -------
    (tier, reason, matched_categories)
        tier: TIER_1 / TIER_2 / TIER_3 / TIER_4
        reason: human-readable explanation
        matched_categories: semantic category matches (may be empty)
    """
    name = evidence.canonical_name

    # --- Step 0: Check for noise / trash ---
    if is_spam_phrase(name):
        return TIER_4, f"'{name}' matches known spam phrase pattern", []

    entropy = compute_phrase_entropy(name)
    if entropy < 0.15:
        return TIER_4, f"'{name}' has very low lexical information ({entropy:.2f})", []

    # --- Step 1: Semantic gravity check ---
    gravity_score, categories = compute_semantic_gravity(name)

    # --- Step 2: TIER_1 — External reality ---
    # Requires semantic gravity AND at least one of: news, strong X, multi-source
    if gravity_score >= 0.6:
        if evidence.has_news_corroboration or evidence.news_article_count >= 1:
            return (
                TIER_1,
                f"High-gravity term '{name}' ({', '.join(categories)}) "
                f"corroborated by news ({evidence.news_article_count} articles)",
                categories,
            )
        if (
            evidence.has_x_corroboration
            and evidence.x_author_count >= X_MIN_AUTHORS_FOR_T2
            and evidence.x_total_engagement >= X_MIN_ENGAGEMENT_FOR_T2
        ):
            return (
                TIER_1,
                f"High-gravity term '{name}' ({', '.join(categories)}) "
                f"with strong X signal ({evidence.x_author_count} authors, "
                f"{evidence.x_total_engagement} engagement)",
                categories,
            )
        # High semantic gravity but weak evidence → still T2 at least
        if evidence.has_x_corroboration or evidence.token_count >= 5:
            return (
                TIER_2,
                f"Gravity term '{name}' ({', '.join(categories)}) "
                f"with moderate evidence ({evidence.token_count} tokens)",
                categories,
            )

    # --- Step 3: TIER_2 — Strong social momentum ---
    if evidence.has_x_corroboration:
        is_strong_x = (
            evidence.x_author_count >= X_STRONG_AUTHORS
            or evidence.x_total_engagement >= X_STRONG_ENGAGEMENT
            or evidence.x_post_count >= X_STRONG_POSTS
        )
        meets_t2_min = (
            evidence.x_author_count >= X_MIN_AUTHORS_FOR_T2
            and evidence.x_total_engagement >= X_MIN_ENGAGEMENT_FOR_T2
            and evidence.x_post_count >= X_MIN_POSTS_FOR_T2
        )
        if is_strong_x:
            return (
                TIER_2,
                f"Strong X signal for '{name}': "
                f"{evidence.x_author_count} authors, "
                f"{evidence.x_total_engagement} engagement, "
                f"{evidence.x_post_count} posts",
                categories,
            )
        if meets_t2_min and evidence.token_count >= 3:
            return (
                TIER_2,
                f"Social + token convergence for '{name}': "
                f"{evidence.x_author_count} X authors + "
                f"{evidence.token_count} tokens",
                categories,
            )

    # Also allow TIER_2 for multi-source convergence without strong X
    if (
        len(evidence.source_types) >= 2
        and evidence.token_count >= 5
        and (evidence.has_x_corroboration or evidence.has_news_corroboration)
    ):
        return (
            TIER_2,
            f"Multi-source convergence for '{name}': "
            f"{len(evidence.source_types)} source types, "
            f"{evidence.token_count} tokens",
            categories,
        )

    # --- Step 4: TIER_3 — Token-echo (token-only) ---
    # Only gets here if no external corroboration OR corroboration too weak
    if evidence.token_count >= 3:
        # Check if it's still too spammy
        anti_spam = compute_anti_spam_score(
            name, evidence.token_names,
            evidence.x_spike_corroboration, evidence.news_corroboration,
        )
        if anti_spam < 0.2:
            return (
                TIER_4,
                f"Token-only term '{name}' with high spam score ({anti_spam:.2f})",
                categories,
            )
        return (
            TIER_3,
            f"Token-echo narrative '{name}': "
            f"{evidence.token_count} tokens, no external corroboration",
            categories,
        )

    # --- Step 5: TIER_4 — Noise ---
    return (
        TIER_4,
        f"Insufficient evidence for '{name}': "
        f"{evidence.token_count} tokens, no corroboration",
        categories,
    )


# ---------------------------------------------------------------------------
# Convenience: build evidence from a NarrativeCandidate
# ---------------------------------------------------------------------------

def evidence_from_candidate(candidate: "NarrativeCandidate") -> NarrativeEvidence:
    """Build a NarrativeEvidence from a NarrativeCandidate's state.

    This bridges the discovery engine's candidate objects to the tier
    classification system.
    """
    source_types: set[str] = {"token_stream"}
    if candidate.x_spike_corroboration > 0:
        source_types.add("social_media")
    if candidate.news_corroboration > 0:
        source_types.add("news")

    return NarrativeEvidence(
        canonical_name=candidate.canonical_name,
        token_count=candidate.token_count,
        token_names=candidate.linked_token_names[:20],
        has_x_corroboration=candidate.x_spike_corroboration > 0,
        x_spike_corroboration=candidate.x_spike_corroboration,
        x_author_count=candidate.x_author_count,
        x_total_engagement=candidate.x_total_engagement,
        x_post_count=candidate.x_post_count,
        has_news_corroboration=candidate.news_corroboration > 0,
        news_corroboration=candidate.news_corroboration,
        news_article_count=candidate.news_article_count,
        news_domain_count=len(candidate.news_domains),
        source_types=source_types,
    )
