"""Links tokens to narratives by running name matching and managing TokenNarrativeLink records.

Reference: docs/intelligence/narrative-linking.md
Reference: docs/implementation/data-model.md — TokenNarrativeLink entity

This module provides the ``CorrelationEngine`` which orchestrates deterministic
name matching (Layers 1-3) and OG resolution for incoming tokens and narratives.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from mctrend.config.settings import Settings
from mctrend.correlation.name_matching import match_token_to_narrative
from mctrend.correlation.og_resolver import resolve_og_candidates

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load configurable minimum confidence from settings
# ---------------------------------------------------------------------------

_settings = Settings.load()
_DEFAULT_MIN_CONFIDENCE: float = _settings.correlation.min_match_confidence


class CorrelationEngine:
    """Matches tokens against active narratives and creates link records.

    Operates purely on deterministic matching layers (1-3).
    Layer 4 (semantic / LLM-assisted) is not invoked here — it is handled
    by a separate module per docs/implementation/agent-strategy.md.
    """

    def __init__(self, min_confidence: float | None = None) -> None:
        self.min_confidence = (
            min_confidence if min_confidence is not None else _DEFAULT_MIN_CONFIDENCE
        )

    def correlate_token(
        self, token: dict, active_narratives: list[dict]
    ) -> list[dict]:
        """Match a single token against all active narratives.

        Parameters
        ----------
        token
            Dict with at least ``name``, ``symbol``, ``token_id``.
        active_narratives
            List of dicts each with ``narrative_id``, ``anchor_terms``,
            ``related_terms``.

        Returns
        -------
        list[dict]
            ``TokenNarrativeLink`` dicts for every match whose confidence
            meets or exceeds ``self.min_confidence``.
        """
        links: list[dict] = []

        # Reject spam/promotional token names upfront
        token_name = token.get("name", "")
        if _is_spam_token_name(token_name):
            logger.info(
                "token_rejected_spam_name",
                token_id=token["token_id"],
                token_name=token_name,
            )
            return []

        for narrative in active_narratives:
            result = match_token_to_narrative(
                token_name=token["name"],
                token_symbol=token["symbol"],
                anchor_terms=narrative["anchor_terms"],
                related_terms=narrative["related_terms"],
            )

            # Check minimum confidence threshold
            if not result["matched"] or result["confidence"] < self.min_confidence:
                continue

            # Reject weak abbreviation/related-term matches
            if result["method"] in ("abbreviation", "related_term"):
                if _is_weak_abbreviation_match(
                    token["name"], result.get("matched_term", ""), result["confidence"]
                ):
                    logger.info(
                        "token_narrative_link_rejected",
                        token_id=token["token_id"],
                        narrative_id=narrative["narrative_id"],
                        reason="weak_abbreviation_match",
                        method=result["method"],
                        confidence=round(result["confidence"], 3),
                        matched_term=result.get("matched_term", ""),
                    )
                    continue

            link = _build_link(
                token_id=token["token_id"],
                narrative_id=narrative["narrative_id"],
                match_result=result,
            )
            links.append(link)

            logger.info(
                "token_linked_to_narrative",
                token_id=token["token_id"],
                token_name=token_name,
                narrative_id=narrative["narrative_id"],
                method=result["method"],
                confidence=round(result["confidence"], 3),
                matched_term=result.get("matched_term"),
            )

        return links

    def correlate_narrative(
        self, narrative: dict, tokens: list[dict]
    ) -> list[dict]:
        """Match a new/updated narrative against all recent tokens.

        Reverse direction of ``correlate_token`` — useful when a new narrative
        is detected and needs to be tested against the backlog of recently
        observed tokens.

        Parameters
        ----------
        narrative
            Dict with ``narrative_id``, ``anchor_terms``, ``related_terms``.
        tokens
            List of dicts each with ``name``, ``symbol``, ``token_id``.

        Returns
        -------
        list[dict]
            ``TokenNarrativeLink`` dicts for every match above threshold.
        """
        links: list[dict] = []

        for token in tokens:
            # Reject spam/promotional token names upfront
            token_name = token.get("name", "")
            if _is_spam_token_name(token_name):
                logger.debug(
                    "token_rejected_spam_name",
                    token_id=token["token_id"],
                    token_name=token_name,
                )
                continue

            result = match_token_to_narrative(
                token_name=token["name"],
                token_symbol=token["symbol"],
                anchor_terms=narrative["anchor_terms"],
                related_terms=narrative["related_terms"],
            )

            if not result["matched"] or result["confidence"] < self.min_confidence:
                continue

            # Reject weak abbreviation/related-term matches
            if result["method"] in ("abbreviation", "related_term"):
                if _is_weak_abbreviation_match(
                    token["name"], result.get("matched_term", ""), result["confidence"]
                ):
                    logger.debug(
                        "token_narrative_link_rejected",
                        token_id=token["token_id"],
                        narrative_id=narrative["narrative_id"],
                        reason="weak_abbreviation_match",
                        method=result["method"],
                        confidence=round(result["confidence"], 3),
                    )
                    continue

            link = _build_link(
                token_id=token["token_id"],
                narrative_id=narrative["narrative_id"],
                match_result=result,
            )
            links.append(link)

            logger.info(
                "narrative_linked_to_token",
                narrative_id=narrative["narrative_id"],
                token_id=token["token_id"],
                token_name=token_name,
                method=result["method"],
                confidence=round(result["confidence"], 3),
                matched_term=result.get("matched_term"),
            )

        return links

    def resolve_namespace(
        self,
        links: list[dict],
        token_launch_times: dict[str, datetime],
    ) -> list[dict]:
        """Run OG resolution on links belonging to the same narrative.

        Parameters
        ----------
        links
            ``TokenNarrativeLink`` dicts that share the same ``narrative_id``.
            Each must have ``token_id``, ``match_confidence``, ``match_method``.
        token_launch_times
            Mapping from ``token_id`` to its ``launch_time`` (datetime, UTC).

        Returns
        -------
        list[dict]
            The same links annotated with ``og_rank``, ``og_score``, and
            ``og_signals``.
        """
        if not links:
            return links

        if len(links) == 1:
            # Single token in namespace — it is the OG by default
            link = dict(links[0])
            link["og_rank"] = 1
            link["og_score"] = None  # Not meaningful with a single candidate
            link["og_signals"] = ["sole_candidate"]
            return [link]

        # Determine earliest launch time as the reference point
        launch_times_for_candidates = {
            link["token_id"]: token_launch_times[link["token_id"]]
            for link in links
            if link["token_id"] in token_launch_times
        }

        if not launch_times_for_candidates:
            logger.warning(
                "No launch times available for namespace resolution; "
                "returning links without OG annotation"
            )
            return links

        earliest = min(launch_times_for_candidates.values())

        # Build candidate dicts for the resolver
        candidates: list[dict] = []
        for link in links:
            token_id = link["token_id"]
            launch_dt = launch_times_for_candidates.get(token_id)

            if launch_dt is None:
                # Missing launch time — conservative: treat as very late entry
                minutes_after = _settings.og_resolution.temporal_decay_minutes
            else:
                delta = (launch_dt - earliest).total_seconds() / 60.0
                minutes_after = max(0.0, delta)

            candidates.append(
                {
                    "token_id": token_id,
                    "launch_time_minutes_after_first": minutes_after,
                    "match_confidence": link["match_confidence"],
                    "match_method": link["match_method"],
                    # Default to 0 cross-source mentions if not present
                    "cross_source_mentions": link.get("cross_source_mentions", 0),
                    # Default deployer_score to neutral (0.5) if not present
                    "deployer_score": link.get("deployer_score", 0.5),
                }
            )

        resolved = resolve_og_candidates(candidates)

        # Merge OG resolution results back into the original link dicts
        og_lookup: dict[str, dict] = {r["token_id"]: r for r in resolved}
        annotated_links: list[dict] = []

        for link in links:
            updated = dict(link)
            resolution = og_lookup.get(link["token_id"])
            if resolution is not None:
                updated["og_rank"] = resolution["og_rank"]
                updated["og_score"] = resolution["og_score"]
                updated["og_signals"] = resolution["og_signals"]
            annotated_links.append(updated)

        # Sort by og_rank so the most likely OG is first
        annotated_links.sort(key=lambda x: x.get("og_rank", 999))

        return annotated_links


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_spam_token_name(name: str) -> bool:
    """Detect spam, promotional, or test token names that should be rejected.

    Returns True if the token name matches known spam patterns.
    """
    if not name:
        return True

    clean = name.strip().upper()

    # Reject names starting with special characters (often paired with $)
    if clean and clean[0] in "$#@!":
        return True

    # Reject generic test/demo/fake names
    spam_keywords = {
        "TEST", "FAKE", "DEMO", "EXAMPLE", "SCAM", "RUG", "HONEYPOT",
        "PLACEHOLDER", "DUMMY", "TEMP", "XXX", "ZZZ",
    }
    if clean in spam_keywords:
        return True

    # Reject generic single letters or short repeated chars
    if len(clean) <= 2 and (all(c == clean[0] for c in clean) or clean == "OK" or clean == "NO"):
        return True

    return False


def _is_weak_abbreviation_match(token_name: str, anchor_term: str, confidence: float) -> bool:
    """Determine if this abbreviation match is too weak and should be rejected.

    Rejects:
    - Very short token names matching longer anchors (e.g., "A" matching "ADOPTION")
    - Single-letter matches
    - Matches where the token is just the first 2 chars of a much longer anchor

    Returns True if the match should be rejected (is too weak).
    """
    tn = token_name.strip().upper().replace(" ", "").replace("-", "").replace("_", "")
    at = anchor_term.strip().upper().replace(" ", "").replace("-", "").replace("_", "")

    # Reject single-letter matches entirely
    if len(tn) <= 1:
        return True

    # Reject 2-char matches against much longer anchors (e.g., "AI" vs "ARTIFICIAL_INTELLIGENCE")
    # Only allow if confidence is high (> 0.70) or the prefix is at least 1/3 of anchor length
    if len(tn) == 2 and len(at) > 8 and confidence < 0.70:
        return True

    # Reject very weak related-term matches (confidence < 0.40)
    # These are often false positives (e.g., "T" matching "TOKEN")
    if confidence < 0.40 and len(tn) < 3:
        return True

    return False


def _build_link(token_id: str, narrative_id: str, match_result: dict) -> dict:
    """Construct a ``TokenNarrativeLink`` dict.

    Schema reference: docs/implementation/data-model.md — TokenNarrativeLink.
    """
    now = datetime.now(timezone.utc)
    return {
        "link_id": str(uuid.uuid4()),
        "token_id": token_id,
        "narrative_id": narrative_id,
        "match_confidence": match_result["confidence"],
        "match_method": match_result["method"],
        "match_signals": match_result["signals"],
        "og_rank": None,
        "og_score": None,
        "og_signals": None,
        "created_at": now,
        "updated_at": now,
        "status": "active",
    }
