"""
Main processing pipeline: orchestrates the full flow from ingestion to alert delivery.

This is the central coordinator. It does not contain business logic — it calls
the appropriate layer for each step.

Flow:
  1. Ingest tokens and events from sources
  2. Normalize raw data into canonical records
  3. Correlate tokens with narratives (name matching + OG resolution)
  4. Score each linked token across 6 dimensions
  5. Classify and manage alerts
  6. Deliver alerts to configured channels
"""

import asyncio
from datetime import datetime, timezone

import structlog

from mctrend.alerting.engine import AlertEngine
from mctrend.correlation.linker import CorrelationEngine
from mctrend.delivery.channels import DeliveryRouter
from mctrend.ingestion.manager import IngestionManager
from mctrend.normalization.normalizer import (
    merge_narratives,
    normalize_chain_snapshot,
    normalize_event,
    normalize_token,
)
from mctrend.persistence.database import Database
from mctrend.persistence.repositories import (
    AlertRepository,
    LinkRepository,
    NarrativeRepository,
    ScoringRepository,
    SourceGapRepository,
    TokenRepository,
)
from mctrend.scoring.aggregator import ScoringAggregator

logger = structlog.get_logger(__name__)


class Pipeline:
    """Full processing pipeline from ingestion to delivery."""

    def __init__(
        self,
        db: Database,
        ingestion: IngestionManager,
        correlator: CorrelationEngine,
        scorer: ScoringAggregator,
        alert_engine: AlertEngine,
        delivery: DeliveryRouter,
    ):
        self.db = db
        self.ingestion = ingestion
        self.correlator = correlator
        self.scorer = scorer
        self.alert_engine = alert_engine
        self.delivery = delivery

        # Repositories
        self.token_repo = TokenRepository(db)
        self.narrative_repo = NarrativeRepository(db)
        self.link_repo = LinkRepository(db)
        self.scoring_repo = ScoringRepository(db)
        self.alert_repo = AlertRepository(db)
        self.gap_repo = SourceGapRepository(db)

        # Stats
        self._cycle_count = 0
        self._total_tokens_processed = 0
        self._total_alerts_generated = 0

    async def run_cycle(self) -> dict:
        """
        Execute one full processing cycle.

        Returns a summary dict with counts and status.
        """
        self._cycle_count += 1
        cycle_start = datetime.now(timezone.utc)
        logger.info("pipeline_cycle_start", cycle=self._cycle_count)

        summary = {
            "cycle": self._cycle_count,
            "started_at": cycle_start.isoformat(),
            "tokens_ingested": 0,
            "events_ingested": 0,
            "links_created": 0,
            "tokens_scored": 0,
            "alerts_created": 0,
            "alerts_delivered": 0,
            "errors": [],
        }

        try:
            # --- Step 1: Ingest ---
            raw_tokens = await self.ingestion.fetch_tokens()
            raw_events = await self.ingestion.fetch_events()

            # Record source gaps
            for gap in self.ingestion.get_pending_gaps():
                self.gap_repo.open_gap(gap)

            # --- Step 2: Normalize and store tokens ---
            new_tokens = []
            for raw in raw_tokens:
                normalized = normalize_token(raw)
                if normalized is None:
                    continue

                # Check for duplicate by address
                existing = self.token_repo.get_by_address(normalized["address"])
                if existing:
                    continue  # Already known

                self.token_repo.save(normalized)
                new_tokens.append(normalized)

            summary["tokens_ingested"] = len(new_tokens)

            # --- Step 3: Normalize and store events/narratives ---
            new_events = []
            for raw in raw_events:
                normalized = normalize_event(raw)
                if normalized is None:
                    continue

                # Check for existing narrative with overlapping terms
                existing = self._find_matching_narrative(normalized["anchor_terms"])
                if existing:
                    # Merge into existing narrative
                    merged = merge_narratives(existing, raw)
                    self.narrative_repo.save(merged)
                else:
                    self.narrative_repo.save(normalized)
                    new_events.append(normalized)

            summary["events_ingested"] = len(new_events)

            # --- Step 4: Correlate tokens with narratives ---
            active_narratives = self.narrative_repo.get_active(
                states=["EMERGING", "PEAKING"]
            )
            # Get recently ingested tokens (status = "new")
            tokens_to_correlate = self.token_repo.list_by_status("new", limit=200)

            links_created = 0
            for token in tokens_to_correlate:
                links = self.correlator.correlate_token(token, active_narratives)
                for link in links:
                    # Check if link already exists
                    existing_links = self.link_repo.get_for_token(token["token_id"])
                    already_linked = any(
                        el.get("narrative_id") == link["narrative_id"]
                        for el in existing_links
                    )
                    if not already_linked:
                        self.link_repo.save(link)
                        links_created += 1

                # Update token status if linked
                token_links = self.link_repo.get_for_token(token["token_id"])
                if token_links:
                    self.token_repo.update_status(
                        token["token_id"], "linked", "narrative_correlated"
                    )

            # OG resolution for namespaces with multiple tokens
            for narrative in active_narratives:
                nid = narrative.get("narrative_id", narrative.get("id", ""))
                namespace_links = self.link_repo.get_active_for_narrative(nid)
                if len(namespace_links) > 1:
                    # Build candidate info and resolve
                    token_launch_times = {}
                    for link in namespace_links:
                        tok = self.token_repo.get_by_id(link["token_id"])
                        if tok:
                            token_launch_times[link["token_id"]] = tok.get("launch_time", "")

                    resolved = self.correlator.resolve_namespace(
                        namespace_links, token_launch_times
                    )
                    for updated_link in resolved:
                        self.link_repo.save(updated_link)

            summary["links_created"] = links_created

            # --- Step 5: Score linked tokens ---
            linked_tokens = self.token_repo.list_by_status("linked", limit=200)
            scored_count = 0

            for token in linked_tokens:
                token_links = self.link_repo.get_for_token(token["token_id"])
                for link in token_links:
                    if link.get("status") != "active":
                        continue

                    narrative = self.narrative_repo.get_by_id(link["narrative_id"])
                    if narrative is None:
                        continue

                    # Build data packages for scorer
                    snapshot = self.token_repo.get_latest_snapshot(token["token_id"])
                    chain_data = self._build_chain_data(token, snapshot)
                    narrative_data = self._build_narrative_data(narrative, link)
                    social_data = {}  # Would come from social adapters
                    link_data = self._build_link_data(link)

                    scored = self.scorer.score_token(
                        token_id=token["token_id"],
                        narrative_id=link["narrative_id"],
                        link_id=link["link_id"],
                        chain_data=chain_data,
                        narrative_data=narrative_data,
                        social_data=social_data,
                        link_data=link_data,
                    )

                    self.scoring_repo.save(scored)
                    scored_count += 1

                    # --- Step 6: Alert classification ---
                    alert = self.alert_engine.process_scored_token(
                        scored_token=scored,
                        token=token,
                        narrative=narrative,
                        link=link,
                    )

                    if alert:
                        summary["alerts_created"] += 1
                        self._total_alerts_generated += 1

                        # --- Step 7: Deliver ---
                        logs = await self.delivery.deliver_alert(alert)
                        summary["alerts_delivered"] += len(
                            [l for l in logs if l.get("status") == "delivered"]
                        )

                # Update token status to scored
                self.token_repo.update_status(
                    token["token_id"], "scored", "scoring_complete"
                )

            summary["tokens_scored"] = scored_count
            self._total_tokens_processed += scored_count

            # --- Step 8: Check expired alerts ---
            expired = self.alert_engine.check_expired_alerts()
            for exp_alert in expired:
                logger.info(
                    "alert_expired",
                    alert_id=exp_alert.get("alert_id"),
                    type=exp_alert.get("alert_type"),
                )

        except Exception as e:
            logger.error("pipeline_cycle_error", error=str(e), cycle=self._cycle_count)
            summary["errors"].append(str(e))

        elapsed = (datetime.now(timezone.utc) - cycle_start).total_seconds()
        summary["elapsed_seconds"] = round(elapsed, 2)
        logger.info("pipeline_cycle_complete", **summary)

        return summary

    def get_stats(self) -> dict:
        """Return pipeline statistics."""
        return {
            "cycles_completed": self._cycle_count,
            "total_tokens_processed": self._total_tokens_processed,
            "total_alerts_generated": self._total_alerts_generated,
            "source_health": self.ingestion.get_source_health(),
            "active_alerts": len(self.alert_repo.get_active()),
            "open_source_gaps": len(self.gap_repo.get_open_gaps()),
        }

    # --- Data building helpers ---

    def _find_matching_narrative(self, anchor_terms: list[str]) -> dict | None:
        """Find an existing narrative that shares anchor terms."""
        for term in anchor_terms:
            results = self.narrative_repo.search_by_terms([term])
            if results:
                return results[0]
        return None

    def _build_chain_data(self, token: dict, snapshot: dict | None) -> dict:
        """Build chain_data dict for the scorer from token + snapshot."""
        data = {
            "deployer_known_bad": False,
            "deployer_prior_deployments": None,
            "mint_authority_status": token.get("mint_authority_status", "unknown"),
            "freeze_authority_status": token.get("freeze_authority_status", "unknown"),
        }

        if snapshot:
            data.update({
                "holder_count": snapshot.get("holder_count"),
                "top_5_holder_pct": snapshot.get("top_5_holder_pct"),
                "top_10_holder_pct": snapshot.get("top_10_holder_pct"),
                "new_wallet_holder_pct": snapshot.get("new_wallet_holder_pct"),
                "liquidity_usd": snapshot.get("liquidity_usd"),
                "liquidity_locked": snapshot.get("liquidity_locked"),
                "liquidity_lock_hours": snapshot.get("liquidity_lock_hours"),
                "liquidity_provider_count": snapshot.get("liquidity_provider_count"),
                "volume_1h_usd": snapshot.get("volume_1h_usd"),
                "trade_count_1h": snapshot.get("trade_count_1h"),
                "unique_traders_1h": snapshot.get("unique_traders_1h"),
                "deployer_known_bad": snapshot.get("deployer_known_bad", False),
                "deployer_prior_deployments": snapshot.get("deployer_prior_deployments"),
            })

        return data

    def _build_narrative_data(self, narrative: dict, link: dict) -> dict:
        """Build narrative_data dict for the scorer."""
        first_detected = narrative.get("first_detected", "")
        now = datetime.now(timezone.utc)

        # Calculate narrative age in hours
        age_hours = 0.0
        if first_detected:
            try:
                fd = datetime.fromisoformat(first_detected.replace("Z", "+00:00"))
                if fd.tzinfo is None:
                    fd = fd.replace(tzinfo=timezone.utc)
                age_hours = (now - fd).total_seconds() / 3600
            except (ValueError, TypeError):
                pass

        return {
            "match_confidence": link.get("match_confidence", 0.5),
            "narrative_age_hours": age_hours,
            "source_type_count": narrative.get("source_type_count", 1),
            "state": narrative.get("state", "EMERGING"),
            "attention_score": narrative.get("attention_score", 0.5),
            "narrative_velocity": narrative.get("narrative_velocity", 0.0),
        }

    def _build_link_data(self, link: dict) -> dict:
        """Build link_data dict for the scorer."""
        return {
            "og_rank": link.get("og_rank"),
            "og_score": link.get("og_score"),
            "cross_source_mentions": 0,  # Would come from cross-source analysis
            "match_method": link.get("match_method", "exact"),
        }
