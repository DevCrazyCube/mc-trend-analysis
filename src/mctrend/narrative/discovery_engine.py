"""Source-agnostic narrative discovery engine.

PRIMARY DISCOVERY: token stream (repeated patterns across token names/symbols).
CORROBORATION: X spikes and other sources boost confidence but do not create candidates.

Architecture
------------
TokenStreamNarrativeExtractor
    Stateless.  Given a list of token records, returns canonical_term →
    (raw_form, [token_ids]) for every term that appears in 2+ distinct tokens.

NarrativeCandidate
    Stateful record for a single candidate narrative.  Tracks token links,
    windowed observations (for velocity), and corroboration from external sources.
    The candidate_id is a deterministic hash of canonical_name so the same entity
    gets the same ID across cycles.

NarrativeDiscoveryEngine
    Orchestrator.  Maintains a dict of candidates across pipeline cycles.
    Each cycle:
      1. process_token_batch(tokens) — update candidates from new/recent tokens
      2. apply_x_corroboration(spikes) — boost existing candidates from X spikes
      3. get_emerging_candidates() — return candidates above threshold
      4. prune() — discard decayed candidates

candidate_to_narrative_event(candidate)
    Converts a NarrativeCandidate to a narrative event dict compatible with
    normalize_event().  Source type is "token_stream" so it participates in
    the standard narrative pipeline with correct source diversity accounting.

Design decisions
----------------
* X is NOT primary — a spike entity that has no corresponding token-stream
  candidate does not become a token-stream narrative event.  It may still
  produce its own x_spike_detection event through the existing spike_correlator
  path.  This keeps the two paths cleanly separated.
* candidate_id is stable across restarts (hash of canonical_name) so future
  persistent storage can correlate candidates across sessions without UUIDs.
* All thresholds are constructor parameters — no hardcoded values in logic.

Reference: docs/ingestion/x-emergent-narrative-detection.md (source context)
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

import structlog

from mctrend.narrative.entity_extraction import (
    DEFAULT_CHRONIC_TERMS,
    canonicalize,
    trigram_jaccard,
)
from mctrend.normalization.normalizer import normalize_token_name

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Noise vocabulary — terms that are always present in the Pump.fun token
# space and therefore never constitute a narrative signal by themselves.
# ---------------------------------------------------------------------------

TOKEN_NOISE_TERMS: frozenset[str] = frozenset({
    # Crypto infrastructure always present
    "BITCOIN", "BTC", "ETHEREUM", "ETH", "SOLANA", "SOL",
    "CRYPTO", "BLOCKCHAIN", "NFT", "NFTS", "DEFI", "WEB3",
    # Generic token words (already stripped by normalize_token_name, kept here
    # as a belt-and-suspenders guard after camelCase splitting)
    "TOKEN", "COIN", "MEMECOIN", "MEME", "FINANCE", "PROTOCOL",
    "CHAIN", "SWAP", "BRIDGE", "VAULT", "AI",
    # Pump.fun specific
    "PUMP", "FUN", "PUMPFUN", "PUMPPORTAL",
    # Very short / always-present generic words
    "THE", "OF", "AND", "OR", "TO", "IN", "FOR", "ON", "AT",
    "INU",  # common memecoin suffix, not a narrative on its own
}) | DEFAULT_CHRONIC_TERMS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _candidate_id(canonical_name: str) -> str:
    """Deterministic, stable candidate ID from canonical name."""
    return "nc-" + hashlib.sha256(canonical_name.encode()).hexdigest()[:12]


def _split_token_name_into_terms(name: str) -> list[str]:
    """Split a token name into individual canonical term candidates.

    Handles:
    - Space-separated: "TRUMP COIN" → ["TRUMP", "COIN"]
    - CamelCase:       "TrumpCoin"  → ["TRUMP", "COIN"]
    - Hyphen/under:    "TRUMP-COIN" → ["TRUMP", "COIN"]
    - Leading specials: "$TRUMP"    → ["TRUMP"]
    - ALL_CAPS single word: "DOGWIF" → ["DOGWIF"]

    Returns canonical (uppercased, $#@-stripped) terms; duplicates removed.
    """
    s = name.strip()
    # Strip leading specials
    while s and s[0] in "$#@!":
        s = s[1:].lstrip()

    # CamelCase boundary insertion: "TrumpCoin" → "Trump Coin"
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    s = re.sub(r"([A-Z]{2,})([A-Z][a-z])", r"\1 \2", s)

    # Split on common separators
    parts = re.split(r"[\s\-_./|\\]+", s)

    seen: set[str] = set()
    terms: list[str] = []
    for p in parts:
        c = canonicalize(p)
        if c and c not in seen:
            seen.add(c)
            terms.append(c)

    return terms


def _parse_launch_timestamp(token: dict) -> float | None:
    """Extract unix timestamp from a token's launch_time field."""
    raw = token.get("launch_time")
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw) / 1000.0 if raw > 1e12 else float(raw)
    if isinstance(raw, str):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except (ValueError, TypeError):
            return None
    return None


# ---------------------------------------------------------------------------
# NarrativeCandidate
# ---------------------------------------------------------------------------

@dataclass
class NarrativeCandidate:
    """A potential narrative derived from recurring patterns in the token stream.

    Lifecycle states
    ----------------
    nascent   — seen in fewer tokens than min_token_count
    emerging  — meets min_token_count, confidence above threshold
    rising    — velocity increasing
    saturated — stable activity, not growing
    decayed   — no new token mentions in decay window
    """

    candidate_id: str
    canonical_name: str
    aliases: set[str] = field(default_factory=set)

    # Token linkage (ordered by observation time)
    linked_token_ids: list[str] = field(default_factory=list)
    linked_token_names: list[str] = field(default_factory=list)

    # Time tracking (unix timestamps)
    first_seen: float = field(
        default_factory=lambda: datetime.now(timezone.utc).timestamp()
    )
    last_seen: float = field(
        default_factory=lambda: datetime.now(timezone.utc).timestamp()
    )

    # Windowed observations: (timestamp, token_count_increment)
    # Used for velocity and emergence score computation.
    _observations: list[tuple[float, int]] = field(default_factory=list)

    # External corroboration (additive boosts, capped at 1.0)
    x_spike_corroboration: float = 0.0
    news_corroboration: float = 0.0

    # X evidence metadata (populated by apply_x_corroboration)
    x_author_count: int = 0
    x_total_engagement: int = 0
    x_post_count: int = 0

    # News evidence metadata (populated by apply_news_corroboration)
    news_article_count: int = 0
    news_domains: set[str] = field(default_factory=set)

    # Lifecycle state label (informational — does not gate processing)
    state: str = "nascent"

    def add_token(
        self,
        token_id: str,
        token_name: str,
        obs_time: float | None = None,
    ) -> bool:
        """Record a token that mentions this candidate's term.

        Returns True if the token was new (not already linked), False if duplicate.
        """
        if token_id in self.linked_token_ids:
            return False
        if obs_time is None:
            obs_time = datetime.now(timezone.utc).timestamp()
        self.linked_token_ids.append(token_id)
        self.linked_token_names.append(token_name)
        self._observations.append((obs_time, 1))
        self.last_seen = max(self.last_seen, obs_time)
        return True

    def add_alias(self, raw_form: str) -> None:
        """Record an alternative raw form for this candidate."""
        self.aliases.add(raw_form)

    def add_x_corroboration(
        self,
        spike_ratio: float,
        match_confidence: float,
        unique_authors: int = 0,
        engagement_total: int = 0,
        mention_count: int = 0,
    ) -> None:
        """Boost confidence from an X spike that matches this candidate.

        Non-destructive: takes the max (so multiple spikes don't double-count).
        Also accumulates X evidence metrics for tier classification.
        """
        boost = min(1.0, (spike_ratio / 20.0) * match_confidence)
        if boost > self.x_spike_corroboration:
            self.x_spike_corroboration = boost

        # Accumulate X evidence (take max for author/engagement, sum for posts)
        self.x_author_count = max(self.x_author_count, unique_authors)
        self.x_total_engagement = max(self.x_total_engagement, engagement_total)
        self.x_post_count = max(self.x_post_count, mention_count)

    def add_news_corroboration(
        self,
        corroboration_score: float,
        article_count: int = 1,
        domain: str = "",
    ) -> None:
        """Record news evidence for this candidate.

        Takes the max corroboration score (non-destructive).
        Accumulates article count and distinct domains.
        """
        self.news_corroboration = max(self.news_corroboration, corroboration_score)
        self.news_article_count = max(self.news_article_count, article_count)
        if domain:
            self.news_domains.add(domain)

    # ------------------------------------------------------------------
    # Derived metrics
    # ------------------------------------------------------------------

    @property
    def token_count(self) -> int:
        return len(self.linked_token_ids)

    def token_count_in_window(
        self, window_seconds: float, now: float | None = None
    ) -> int:
        if now is None:
            now = datetime.now(timezone.utc).timestamp()
        cutoff = now - window_seconds
        return sum(c for ts, c in self._observations if ts >= cutoff)

    def token_velocity(
        self, window_seconds: float = 1800.0, now: float | None = None
    ) -> float:
        """Tokens per minute in the given window."""
        count = self.token_count_in_window(window_seconds, now)
        minutes = window_seconds / 60.0
        return count / minutes if minutes > 0 else 0.0

    @property
    def age_seconds(self) -> float:
        return datetime.now(timezone.utc).timestamp() - self.first_seen

    def emergence_score(
        self,
        short_window: float = 1800.0,
        baseline_window: float = 21600.0,
        now: float | None = None,
    ) -> float:
        """How quickly is this narrative growing?  Returns 0.0–1.0.

        Computes ratio of short-term token velocity to baseline.  High ratio
        = rapid emergence.  On first cycle (no baseline yet), uses raw count.
        """
        if now is None:
            now = datetime.now(timezone.utc).timestamp()
        short = self.token_count_in_window(short_window, now)
        baseline = self.token_count_in_window(baseline_window, now)
        if baseline == 0:
            # First observation window — normalize against a reference of 5 tokens
            return min(1.0, short / 5.0)
        ratio = short / max(baseline, 1)
        return min(1.0, ratio / 3.0)  # 3× baseline = max emergence

    def confidence(self, now: float | None = None) -> float:
        """Confidence that this is a real narrative (not coincidental noise).

        Components:
        - Token count base:      more tokens → higher base (log scale)
        - X corroboration:       spike match → +0.15 max
        - News corroboration:    news match  → +0.10 max
        - Recency factor:        decays over 2h since last token
        """
        if now is None:
            now = datetime.now(timezone.utc).timestamp()

        # Base from token count (log scale)
        # 1 token → 0.0   (nascent, not a candidate yet)
        # 2 tokens → 0.30  (threshold for candidate emission)
        # 5 tokens → 0.46
        # 10 tokens → 0.56
        # 20+ tokens → ~0.68
        if self.token_count < 2:
            base = 0.0
        else:
            base = min(0.8, 0.3 + 0.1 * math.log1p(self.token_count - 1))

        x_boost = self.x_spike_corroboration * 0.15
        news_boost = self.news_corroboration * 0.10

        # Recency: full confidence if active in last 30 min, linear decay to 0 at 2h
        time_since_last = now - self.last_seen
        recency_factor = max(0.0, 1.0 - time_since_last / 7200.0)

        total = (base + x_boost + news_boost) * recency_factor
        return min(1.0, max(0.0, round(total, 4)))

    def prune_observations(
        self, max_age_seconds: float = 86400.0, now: float | None = None
    ) -> None:
        """Remove observations older than max_age_seconds."""
        if now is None:
            now = datetime.now(timezone.utc).timestamp()
        cutoff = now - max_age_seconds
        self._observations = [(ts, c) for ts, c in self._observations if ts >= cutoff]

    def to_dict(self, now: float | None = None) -> dict:
        if now is None:
            now = datetime.now(timezone.utc).timestamp()
        return {
            "candidate_id": self.candidate_id,
            "canonical_name": self.canonical_name,
            "aliases": sorted(self.aliases),
            "token_count": self.token_count,
            "linked_token_ids": self.linked_token_ids[:10],
            "linked_token_names": self.linked_token_names[:10],
            "first_seen": datetime.fromtimestamp(
                self.first_seen, tz=timezone.utc
            ).isoformat(),
            "last_seen": datetime.fromtimestamp(
                self.last_seen, tz=timezone.utc
            ).isoformat(),
            "age_seconds": round(self.age_seconds, 1),
            "x_spike_corroboration": round(self.x_spike_corroboration, 3),
            "x_author_count": self.x_author_count,
            "x_total_engagement": self.x_total_engagement,
            "x_post_count": self.x_post_count,
            "news_corroboration": round(self.news_corroboration, 3),
            "news_article_count": self.news_article_count,
            "news_domain_count": len(self.news_domains),
            "confidence": self.confidence(now),
            "emergence_score": self.emergence_score(now=now),
            "state": self.state,
        }


# ---------------------------------------------------------------------------
# TokenStreamNarrativeExtractor
# ---------------------------------------------------------------------------

def _extract_terms_from_token(token: dict) -> list[tuple[str, str]]:
    """Extract (canonical_term, raw_form) pairs from a single token record.

    Processes: symbol (highest confidence), then name (split into terms).
    Returns deduplicated list; dedup is by canonical form.
    """
    results: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _add(raw: str, label: str) -> None:
        canon = canonicalize(raw)
        if canon and len(canon) >= 2 and canon not in seen:
            seen.add(canon)
            results.append((canon, label))

    # Symbol: whole-token signal (highest confidence)
    symbol = (token.get("symbol") or "").strip()
    if symbol:
        _add(symbol, symbol)

    # Name: split into component terms
    name = (token.get("name") or "").strip()
    if name:
        for term in _split_token_name_into_terms(name):
            _add(term, name)

    return results


class TokenStreamNarrativeExtractor:
    """Extract narrative candidates from the token stream.

    Stateless — given a list of token records, returns a mapping of
    canonical_term → (one_raw_form, [token_ids]) for every term appearing
    in 2+ distinct tokens within the batch.

    This is the PRIMARY discovery mechanism.  No network calls, no LLM,
    no external dependencies beyond the token records themselves.
    """

    def __init__(
        self,
        noise_terms: frozenset[str] | None = None,
        min_term_length: int = 2,
        min_token_occurrences: int = 2,
    ):
        self.noise_terms = noise_terms if noise_terms is not None else TOKEN_NOISE_TERMS
        self.min_term_length = min_term_length
        self.min_token_occurrences = min_token_occurrences

    def extract_from_tokens(
        self,
        tokens: list[dict],
        now: float | None = None,
    ) -> dict[str, tuple[str, list[str]]]:
        """Extract term→token mappings from a list of token records.

        Parameters
        ----------
        tokens
            List of normalized token dicts (must contain token_id, name, symbol).
        now
            Current unix timestamp (for logging only).

        Returns
        -------
        dict mapping canonical_term → (one_raw_form, [token_ids]) where at
        least min_token_occurrences distinct tokens mention the term.
        """
        # term → list of (token_id, raw_form)
        term_occurrences: dict[str, list[tuple[str, str]]] = {}
        term_first_raw: dict[str, str] = {}

        for token in tokens:
            token_id = token.get("token_id", "")
            if not token_id:
                continue

            for canon, raw in _extract_terms_from_token(token):
                if len(canon) < self.min_term_length:
                    continue
                if canon in self.noise_terms:
                    continue
                if canon not in term_occurrences:
                    term_occurrences[canon] = []
                    term_first_raw[canon] = raw
                # De-duplicate same token appearing multiple times
                if not any(tid == token_id for tid, _ in term_occurrences[canon]):
                    term_occurrences[canon].append((token_id, raw))

        return {
            canon: (term_first_raw[canon], [tid for tid, _ in occ])
            for canon, occ in term_occurrences.items()
            if len(occ) >= self.min_token_occurrences
        }


# ---------------------------------------------------------------------------
# NarrativeDiscoveryEngine
# ---------------------------------------------------------------------------

class NarrativeDiscoveryEngine:
    """Orchestrates narrative discovery from the token stream.

    Maintains state across pipeline cycles.  The token stream is the PRIMARY
    discovery source.  X spike corroboration is optional and additive only —
    X cannot create a new candidate, it can only boost an existing one.

    Typical cycle usage
    -------------------
    engine = NarrativeDiscoveryEngine()

    # each pipeline cycle:
    engine.process_token_batch(all_recent_tokens)
    engine.apply_x_corroboration(x_spikes)          # optional
    candidates = engine.get_emerging_candidates()
    events = [candidate_to_narrative_event(c) for c in candidates]
    engine.prune()

    summary = engine.get_summary()
    """

    def __init__(
        self,
        noise_terms: frozenset[str] | None = None,
        min_term_length: int = 2,
        min_token_occurrences: int = 2,
        min_confidence: float = 0.25,
        short_window_seconds: float = 1800.0,
        baseline_window_seconds: float = 21600.0,
        decay_window_seconds: float = 86400.0,
        x_corroboration_similarity_threshold: float = 0.7,
    ):
        self._extractor = TokenStreamNarrativeExtractor(
            noise_terms=noise_terms,
            min_term_length=min_term_length,
            min_token_occurrences=min_token_occurrences,
        )
        self.min_confidence = min_confidence
        self.short_window_seconds = short_window_seconds
        self.baseline_window_seconds = baseline_window_seconds
        self.decay_window_seconds = decay_window_seconds
        self.x_corr_threshold = x_corroboration_similarity_threshold

        # State: canonical_name → NarrativeCandidate
        self._candidates: dict[str, NarrativeCandidate] = {}

    # ------------------------------------------------------------------
    # Primary: token stream processing
    # ------------------------------------------------------------------

    def process_token_batch(
        self,
        tokens: list[dict],
        now: float | None = None,
    ) -> int:
        """Update candidates from a batch of token records.

        Uses launch_time from each token as the observation timestamp so that
        velocity computation reflects actual launch timing, not processing lag.

        Returns the number of new candidate-token links created.
        """
        if not tokens:
            return 0
        if now is None:
            now = datetime.now(timezone.utc).timestamp()

        token_lookup: dict[str, dict] = {
            t.get("token_id", ""): t for t in tokens if t.get("token_id")
        }

        term_map = self._extractor.extract_from_tokens(tokens, now)
        new_links = 0

        for canon, (raw_form, token_ids) in term_map.items():
            if canon not in self._candidates:
                cand = NarrativeCandidate(
                    candidate_id=_candidate_id(canon),
                    canonical_name=canon,
                    first_seen=now,
                    last_seen=now,
                )
                self._candidates[canon] = cand
                logger.debug(
                    "narrative_candidate_created",
                    canonical=canon,
                    initial_tokens=len(token_ids),
                )
            else:
                cand = self._candidates[canon]

            cand.add_alias(raw_form)

            for tid in token_ids:
                token = token_lookup.get(tid, {})
                token_name = token.get("name", tid)
                # Use launch_time for accurate velocity; fall back to now
                obs_time = _parse_launch_timestamp(token) or now
                if cand.add_token(tid, token_name, obs_time):
                    new_links += 1
                    logger.debug(
                        "narrative_candidate_token_linked",
                        canonical=canon,
                        token_id=tid,
                        token_name=token_name,
                        total_tokens=cand.token_count,
                    )

        return new_links

    # ------------------------------------------------------------------
    # Corroboration: X spikes (secondary only)
    # ------------------------------------------------------------------

    def apply_x_corroboration(self, spikes: list[dict]) -> int:
        """Boost existing candidates from X spike signals.

        X is NOT primary discovery.  If a spike entity matches no existing
        candidate it is ignored here (it may still become its own narrative
        event via the spike_correlator path).

        Returns the number of candidates that received a corroboration boost.
        """
        boosted = 0
        for spike in spikes:
            entity = spike.get("entity", "")
            if not entity:
                continue
            spike_ratio = float(spike.get("spike_ratio", 1.0))
            unique_authors = int(spike.get("unique_authors", 0))
            engagement_total = int(spike.get("engagement_total", 0))
            mention_count = int(spike.get("mention_count", 0))

            for canon, cand in self._candidates.items():
                sim = trigram_jaccard(entity, canon)
                exact = entity == canon
                if exact or sim >= self.x_corr_threshold:
                    match_confidence = 1.0 if exact else min(1.0, sim + 0.1)
                    cand.add_x_corroboration(
                        spike_ratio,
                        match_confidence,
                        unique_authors=unique_authors,
                        engagement_total=engagement_total,
                        mention_count=mention_count,
                    )
                    boosted += 1
                    logger.debug(
                        "narrative_candidate_x_corroboration",
                        canonical=canon,
                        spike_entity=entity,
                        similarity=round(sim, 3),
                        spike_ratio=round(spike_ratio, 2),
                        new_x_boost=round(cand.x_spike_corroboration, 3),
                        x_authors=unique_authors,
                        x_engagement=engagement_total,
                    )
        return boosted

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_emerging_candidates(
        self,
        min_token_count: int = 2,
        min_confidence: float | None = None,
        now: float | None = None,
    ) -> list[NarrativeCandidate]:
        """Return candidates meeting emergence criteria, sorted by confidence desc."""
        if now is None:
            now = datetime.now(timezone.utc).timestamp()
        threshold = min_confidence if min_confidence is not None else self.min_confidence

        result = [
            c for c in self._candidates.values()
            if c.token_count >= min_token_count
            and c.confidence(now) >= threshold
        ]
        result.sort(key=lambda c: c.confidence(now), reverse=True)
        return result

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def prune(self, now: float | None = None) -> int:
        """Remove candidates whose last token was seen beyond decay_window.

        Returns number of candidates removed.
        """
        if now is None:
            now = datetime.now(timezone.utc).timestamp()
        cutoff = now - self.decay_window_seconds

        to_remove = []
        for canon, cand in self._candidates.items():
            cand.prune_observations(self.decay_window_seconds, now)
            if cand.last_seen < cutoff:
                to_remove.append(canon)

        for canon in to_remove:
            del self._candidates[canon]

        if to_remove:
            logger.debug(
                "narrative_candidates_pruned",
                count=len(to_remove),
                names=to_remove[:5],
            )
        return len(to_remove)

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def get_summary(self, now: float | None = None) -> dict:
        """Return a cycle-summary dict for logging and dashboard."""
        if now is None:
            now = datetime.now(timezone.utc).timestamp()
        emerging = self.get_emerging_candidates(now=now)
        return {
            "token_stream_candidates_total": len(self._candidates),
            "token_stream_candidates_emerging": len(emerging),
            "token_stream_top_candidates": [
                {
                    "name": c.canonical_name,
                    "tokens": c.token_count,
                    "confidence": c.confidence(now),
                }
                for c in emerging[:5]
            ],
        }


# ---------------------------------------------------------------------------
# candidate_to_narrative_event
# ---------------------------------------------------------------------------

def candidate_to_narrative_event(
    candidate: NarrativeCandidate,
    now: float | None = None,
) -> dict:
    """Convert a NarrativeCandidate to a normalize_event()-compatible dict.

    Source type is "token_stream" so it contributes source diversity when
    combined with news or social signals in the existing narrative pipeline.

    Signal strength is a blend of confidence and emergence score.
    """
    if now is None:
        now = datetime.now(timezone.utc).timestamp()

    published_at = datetime.fromtimestamp(
        candidate.last_seen, tz=timezone.utc
    ).isoformat()

    conf = candidate.confidence(now)
    emergence = candidate.emergence_score(now=now)
    signal_strength = min(1.0, conf * 0.7 + emergence * 0.3)

    # Anchor terms: canonical name first, then distinct short aliases
    anchor_terms = [candidate.canonical_name]
    for alias in sorted(candidate.aliases):
        canon_alias = canonicalize(alias)
        if canon_alias and canon_alias != candidate.canonical_name:
            anchor_terms.append(canon_alias)
            if len(anchor_terms) >= 5:
                break

    # Related terms: normalized token names that referenced this candidate
    related_terms: list[str] = []
    for tname in candidate.linked_token_names[:5]:
        norm = normalize_token_name(tname)
        if norm:
            upper = norm.upper()
            if upper not in anchor_terms:
                related_terms.append(upper)

    description = (
        f"Token stream: '{candidate.canonical_name}' appears in "
        f"{candidate.token_count} recently-launched token(s)"
    )
    if candidate.x_spike_corroboration > 0.0:
        description += (
            f" (X spike corroboration: {candidate.x_spike_corroboration:.2f})"
        )

    return {
        "anchor_terms": anchor_terms,
        "related_terms": related_terms,
        "description": description,
        "source_type": "token_stream",
        "source_name": "token_stream_discovery",
        "signal_strength": round(signal_strength, 4),
        "published_at": published_at,
        # entities must be a list (not dict) for narrative clustering compatibility
        "entities": [],
        "_candidate_metadata": {
            "candidate_id": candidate.candidate_id,
            "canonical_name": candidate.canonical_name,
            "token_count": candidate.token_count,
            "token_ids": candidate.linked_token_ids[:20],
            "confidence": conf,
            "emergence_score": emergence,
            "x_corroboration": candidate.x_spike_corroboration,
        },
    }
