"""Deterministic entity/topic extraction from X (Twitter) content.

Extracts candidate entities from tweet text, normalizes them to canonical
forms, deduplicates variants, and rejects noise.  No LLM -- all logic is
rule-based and inspectable.

Reference: docs/ingestion/x-emergent-narrative-detection.md
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from typing import Iterable

import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

_CASHTAG_RE = re.compile(r"\$([A-Za-z][A-Za-z0-9]{1,11})\b")
_HASHTAG_RE = re.compile(r"#([A-Za-z0-9_]{2,30})\b")
_MENTION_RE = re.compile(r"@([A-Za-z0-9_]{1,15})\b")
_QUOTED_RE = re.compile(r'["\u201c\u201d]([A-Za-z][A-Za-z0-9 ]{1,40})["\u201c\u201d]')
_URL_RE = re.compile(r"https?://\S+")

# Proper noun heuristic: 2+ capitalized words not at sentence start
_PROPER_NOUN_RE = re.compile(
    r"(?<![.!?]\s)(?<!\A)"  # Not sentence start
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b"  # Two+ capitalized words
)

# ---------------------------------------------------------------------------
# Chronic / noise terms
# ---------------------------------------------------------------------------

# Terms that are always present and never emergent.  Configurable via
# XEntityExtractor constructor.
DEFAULT_CHRONIC_TERMS: frozenset[str] = frozenset({
    # Crypto infrastructure (always present, never a spike signal)
    "BITCOIN", "BTC", "ETHEREUM", "ETH", "CRYPTO", "BLOCKCHAIN",
    "NFT", "NFTS", "DEFI", "WEB3", "ALTCOIN", "ALTCOINS",
    # Generic social noise
    "GM", "GN", "WAGMI", "NGMI", "LFG", "DYOR",
    # Common English words that pass stop-word filters but aren't entities
    "BREAKING", "UPDATE", "NEWS", "TODAY", "TONIGHT",
    "PEOPLE", "EVERYONE", "SOMEONE", "SOMETHING",
    "PLEASE", "THANKS", "SORRY",
})

# Minimum term length to be considered a candidate
_MIN_ENTITY_LENGTH = 2

# Maximum number of entities extracted per tweet
_MAX_ENTITIES_PER_TWEET = 10


# ---------------------------------------------------------------------------
# Entity types
# ---------------------------------------------------------------------------

def _classify_entity_type(raw: str, source: str) -> str:
    """Classify an entity by how it was extracted."""
    if source == "cashtag":
        return "cashtag"
    if source == "hashtag":
        return "hashtag"
    if source == "mention":
        return "mention"
    if source == "quoted":
        return "topic"
    if source == "proper_noun":
        return "person"
    return "topic"


# ---------------------------------------------------------------------------
# Canonical form
# ---------------------------------------------------------------------------

def canonicalize(raw: str) -> str:
    """Normalize a raw entity string to canonical form.

    - Strips leading $, #, @
    - Uppercases
    - Strips surrounding whitespace
    """
    s = raw.strip()
    while s and s[0] in "$#@":
        s = s[1:]
    return s.strip().upper()


def _trigram_set(s: str) -> set[str]:
    """Character trigrams for fuzzy matching."""
    s = s.upper()
    if not s:
        return set()
    if len(s) < 3:
        return {s}
    return {s[i:i+3] for i in range(len(s) - 2)}


def trigram_jaccard(a: str, b: str) -> float:
    """Jaccard similarity over character trigrams."""
    sa, sb = _trigram_set(a), _trigram_set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


# ---------------------------------------------------------------------------
# Candidate entity
# ---------------------------------------------------------------------------

class CandidateEntity:
    """A candidate entity extracted from tweet content."""

    __slots__ = (
        "canonical", "entity_type", "variants", "mention_count",
        "author_ids", "engagement_total", "sample_texts", "first_seen",
    )

    def __init__(
        self,
        canonical: str,
        entity_type: str = "topic",
        first_seen: datetime | None = None,
    ):
        self.canonical = canonical
        self.entity_type = entity_type
        self.variants: set[str] = set()
        self.mention_count: int = 0
        self.author_ids: set[str] = set()
        self.engagement_total: float = 0.0
        self.sample_texts: list[str] = []
        self.first_seen: datetime = first_seen or datetime.now(timezone.utc)

    def add_mention(
        self,
        variant: str,
        author_id: str = "",
        engagement: float = 0.0,
        sample_text: str = "",
    ) -> None:
        """Record one mention of this entity."""
        self.variants.add(variant)
        self.mention_count += 1
        if author_id:
            self.author_ids.add(author_id)
        self.engagement_total += engagement
        if sample_text and len(self.sample_texts) < 5:
            self.sample_texts.append(sample_text[:200])

    @property
    def unique_authors(self) -> int:
        return len(self.author_ids)

    def to_dict(self) -> dict:
        return {
            "canonical": self.canonical,
            "entity_type": self.entity_type,
            "variants": sorted(self.variants),
            "mention_count": self.mention_count,
            "unique_authors": self.unique_authors,
            "engagement_total": round(self.engagement_total, 2),
            "first_seen": self.first_seen.isoformat(),
        }


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------

class XEntityExtractor:
    """Extract and normalize candidate entities from tweet content.

    Deterministic, no LLM.  Extracts:
    - Cashtags ($TOKEN)
    - Hashtags (#topic)
    - @mentions (for person-entity linkage)
    - Quoted names ("Operation X")
    - Proper noun bigrams (capitalized multi-word sequences)
    - High-frequency general terms (via term counting)

    Rejects:
    - Chronic terms (always-present, never emergent)
    - Too-short terms
    - Single common English words
    """

    def __init__(
        self,
        chronic_terms: frozenset[str] | None = None,
        min_entity_length: int = _MIN_ENTITY_LENGTH,
        merge_similarity_threshold: float = 0.8,
    ):
        self.chronic_terms = chronic_terms if chronic_terms is not None else DEFAULT_CHRONIC_TERMS
        self.min_entity_length = min_entity_length
        self.merge_threshold = merge_similarity_threshold

    def extract_from_tweet(self, tweet_text: str) -> list[tuple[str, str, str]]:
        """Extract raw entities from a single tweet.

        Returns list of (raw_form, canonical_form, entity_type) tuples.
        """
        results: list[tuple[str, str, str]] = []
        seen: set[str] = set()

        def _add(raw: str, source: str) -> None:
            canon = canonicalize(raw)
            if (
                len(canon) < self.min_entity_length
                or canon in self.chronic_terms
                or canon in seen
            ):
                return
            seen.add(canon)
            etype = _classify_entity_type(raw, source)
            results.append((raw.strip(), canon, etype))

        # Cashtags — highest signal
        for m in _CASHTAG_RE.finditer(tweet_text):
            _add(f"${m.group(1)}", "cashtag")

        # Hashtags
        for m in _HASHTAG_RE.finditer(tweet_text):
            _add(f"#{m.group(1)}", "hashtag")

        # Quoted names
        for m in _QUOTED_RE.finditer(tweet_text):
            _add(m.group(1), "quoted")

        # Proper nouns (multi-word capitalized sequences)
        # Strip URLs and mentions first to avoid false positives
        cleaned = _URL_RE.sub("", tweet_text)
        cleaned = _MENTION_RE.sub("", cleaned)
        for m in _PROPER_NOUN_RE.finditer(cleaned):
            _add(m.group(1), "proper_noun")

        return results[:_MAX_ENTITIES_PER_TWEET]

    def extract_from_tweets(
        self,
        tweets: Iterable[dict],
    ) -> dict[str, CandidateEntity]:
        """Extract and aggregate entities from a batch of tweets.

        Parameters
        ----------
        tweets
            Iterable of event dicts (output of XAPIAdapter._normalize_tweet).
            Expected keys: raw_text, source_name, _engagement_score.

        Returns
        -------
        dict mapping canonical form -> CandidateEntity
        """
        candidates: dict[str, CandidateEntity] = {}

        for tweet in tweets:
            text = tweet.get("raw_text", "")
            author = tweet.get("source_name", "")
            engagement = tweet.get("_engagement_score", 0.0)

            raw_entities = self.extract_from_tweet(text)

            for raw_form, canonical, entity_type in raw_entities:
                if canonical not in candidates:
                    candidates[canonical] = CandidateEntity(
                        canonical=canonical,
                        entity_type=entity_type,
                    )
                candidates[canonical].add_mention(
                    variant=raw_form,
                    author_id=author,
                    engagement=engagement,
                    sample_text=text,
                )

        return candidates

    def merge_similar(
        self, candidates: dict[str, CandidateEntity],
    ) -> dict[str, CandidateEntity]:
        """Merge candidates with high string similarity.

        Uses trigram Jaccard similarity.  The candidate with more mentions
        absorbs the smaller one.
        """
        keys = sorted(candidates.keys())
        merged_into: dict[str, str] = {}  # old_key -> winner_key

        for i, k1 in enumerate(keys):
            if k1 in merged_into:
                continue
            for j in range(i + 1, len(keys)):
                k2 = keys[j]
                if k2 in merged_into:
                    continue
                if trigram_jaccard(k1, k2) >= self.merge_threshold:
                    # Merge smaller into larger
                    c1, c2 = candidates[k1], candidates[k2]
                    if c1.mention_count >= c2.mention_count:
                        winner, loser, loser_key = c1, c2, k2
                    else:
                        winner, loser, loser_key = c2, c1, k1
                    winner.variants |= loser.variants
                    winner.mention_count += loser.mention_count
                    winner.author_ids |= loser.author_ids
                    winner.engagement_total += loser.engagement_total
                    merged_into[loser_key] = winner.canonical

        return {k: v for k, v in candidates.items() if k not in merged_into}

    def reject_noise(
        self,
        candidates: dict[str, CandidateEntity],
        min_mentions: int = 1,
        min_authors: int = 1,
    ) -> dict[str, CandidateEntity]:
        """Remove candidates that are likely noise.

        Returns the filtered dict and logs rejections.
        """
        kept: dict[str, CandidateEntity] = {}

        for canon, cand in candidates.items():
            # Single-character after canonicalization
            if len(canon) < self.min_entity_length:
                logger.debug("x_entity_rejected", entity=canon, reason="too_short")
                continue

            # Chronic terms (double-check after merge)
            if canon in self.chronic_terms:
                logger.debug("x_entity_rejected", entity=canon, reason="chronic_term")
                continue

            # Below minimum mentions
            if cand.mention_count < min_mentions:
                logger.debug(
                    "x_entity_rejected", entity=canon, reason="below_min_mentions",
                    count=cand.mention_count, threshold=min_mentions,
                )
                continue

            # Below minimum unique authors
            if cand.unique_authors < min_authors:
                logger.debug(
                    "x_entity_rejected", entity=canon, reason="below_min_authors",
                    authors=cand.unique_authors, threshold=min_authors,
                )
                continue

            kept[canon] = cand

        rejected = len(candidates) - len(kept)
        if rejected:
            logger.debug("x_entities_rejected_total", count=rejected, kept=len(kept))

        return kept
