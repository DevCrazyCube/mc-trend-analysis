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
  7. Expire stale alerts
  8. Prune old data per retention policy
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import structlog

from mctrend.alerting.classifier import explain_rejection
from mctrend.alerting.engine import AlertEngine
from mctrend.correlation.linker import CorrelationEngine
from mctrend.delivery.channels import DeliveryRouter
from mctrend.ingestion.manager import IngestionManager
from mctrend.narrative.intelligence import (
    NarrativeConfig,
    NarrativeIntelligence,
)
from mctrend.normalization.normalizer import (
    merge_narratives,
    normalize_event,
    normalize_token,
)
from mctrend.persistence.database import Database
from mctrend.persistence.repositories import (
    AlertRepository,
    LinkRepository,
    NarrativeRepository,
    RejectedCandidateRepository,
    ScoringRepository,
    SourceGapRepository,
    TokenRepository,
)
from mctrend.scoring.aggregator import ScoringAggregator

if TYPE_CHECKING:
    from mctrend.config.settings import Settings

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
        settings: "Settings | None" = None,
    ):
        self.db = db
        self.ingestion = ingestion
        self.correlator = correlator
        self.scorer = scorer
        self.alert_engine = alert_engine
        self.delivery = delivery
        self.settings = settings

        # Repositories
        self.token_repo = TokenRepository(db)
        self.narrative_repo = NarrativeRepository(db)
        self.link_repo = LinkRepository(db)
        self.scoring_repo = ScoringRepository(db)
        self.alert_repo = AlertRepository(db)
        self.gap_repo = SourceGapRepository(db)
        self.rejected_repo = RejectedCandidateRepository(db)

        # Narrative intelligence engine
        ni_cfg = NarrativeConfig()
        if settings and hasattr(settings, "narrative_intelligence"):
            ni = settings.narrative_intelligence
            ni_cfg = NarrativeConfig(
                velocity_window_minutes=ni.velocity_window_minutes,
                max_velocity=ni.max_velocity,
                strength_w_source_count=ni.strength_w_source_count,
                strength_w_velocity=ni.strength_w_velocity,
                strength_w_recency=ni.strength_w_recency,
                strength_w_diversity=ni.strength_w_diversity,
                max_source_count=ni.max_source_count,
                recency_decay_minutes=ni.recency_decay_minutes,
                max_source_types=ni.max_source_types,
                min_sources=ni.min_sources,
                weak_threshold=ni.weak_threshold,
                emerging_threshold=ni.emerging_threshold,
                rising_threshold=ni.rising_threshold,
                trending_threshold=ni.trending_threshold,
                trending_min_sources=ni.trending_min_sources,
                fading_threshold=ni.fading_threshold,
                dead_threshold=ni.dead_threshold,
                dead_timeout_minutes=ni.dead_timeout_minutes,
                winner_min_strength=ni.winner_min_strength,
                token_competition_margin=ni.token_competition_margin,
                cluster_term_overlap_pct=ni.cluster_term_overlap_pct,
                cluster_token_overlap_min=ni.cluster_token_overlap_min,
                cluster_min_source_diversity=ni.cluster_min_source_diversity,
            )
        self.narrative_intel = NarrativeIntelligence(ni_cfg)

        # Stats
        self._cycle_count = 0
        self._total_tokens_processed = 0
        self._total_alerts_generated = 0

    async def run_cycle(self) -> dict:
        """Execute one full processing cycle.

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
            "alerts_expired": 0,
            "rows_pruned": 0,
            "errors": [],
        }

        # Step 1: Ingest
        try:
            raw_tokens = await self.ingestion.fetch_tokens()
            raw_events = await self.ingestion.fetch_events()

            # Record source gaps; close any that recovered
            for gap in self.ingestion.get_pending_gaps():
                self.gap_repo.open_gap(gap)

            now_iso = datetime.now(timezone.utc).isoformat()
            for source_name, meta in self.ingestion.get_source_health().items():
                if meta.get("healthy"):
                    closed = self.gap_repo.close_open_gaps_for_source(source_name, now_iso)
                    if closed:
                        logger.info("source_gap_closed",
                                    source=source_name, gaps_closed=closed)
        except Exception as e:
            logger.error("pipeline_ingest_error", error=str(e))
            summary["errors"].append(f"ingest: {e}")
            raw_tokens, raw_events = [], []

        # Step 2: Normalize and store tokens
        new_tokens = []
        for raw in raw_tokens:
            try:
                normalized = normalize_token(raw)
                if normalized is None:
                    continue
                existing = self.token_repo.get_by_address(normalized["address"])
                if existing:
                    continue
                self.token_repo.save(normalized)
                new_tokens.append(normalized)
            except Exception as e:
                logger.error("token_normalization_error",
                             error=str(e), raw=str(raw)[:200])
                summary["errors"].append(f"normalize_token: {e}")

        summary["tokens_ingested"] = len(new_tokens)

        # Step 3: Normalize and store events/narratives
        new_events = []
        for raw in raw_events:
            try:
                normalized = normalize_event(raw)
                if normalized is None:
                    continue
                existing = self._find_matching_narrative(normalized["anchor_terms"])
                if existing:
                    merged = merge_narratives(existing, raw)
                    self.narrative_repo.save(merged)
                else:
                    self.narrative_repo.save(normalized)
                    new_events.append(normalized)
            except Exception as e:
                logger.error("event_normalization_error", error=str(e))
                summary["errors"].append(f"normalize_event: {e}")

        summary["events_ingested"] = len(new_events)

        # Step 3.5: Evaluate all non-terminal narratives through intelligence engine
        # Computes velocity, strength, and lifecycle state for each narrative.
        narratives_evaluated = 0
        try:
            all_narratives = self.narrative_repo.get_active()
            now = datetime.now(timezone.utc)
            for narrative in all_narratives:
                try:
                    updates = self.narrative_intel.transition_narrative(narrative, now)
                    if updates:
                        nid = narrative.get("narrative_id")
                        self.narrative_repo.update_fields(nid, updates)
                        narratives_evaluated += 1
                except Exception as e:
                    logger.error(
                        "narrative_evaluation_error",
                        narrative_id=narrative.get("narrative_id"),
                        error=str(e),
                    )
            if narratives_evaluated:
                logger.info("narratives_evaluated", count=narratives_evaluated)
        except Exception as e:
            logger.error("pipeline_narrative_eval_error", error=str(e))
            summary["errors"].append(f"narrative_eval: {e}")

        summary["narratives_evaluated"] = narratives_evaluated

        # Step 3.6: Cluster narratives for valid competition grouping
        try:
            scoring_narratives = self.narrative_repo.get_for_scoring()
            if scoring_narratives:
                # Build token_links map for token-overlap clustering
                narr_token_links: dict[str, list[str]] = {}
                for narr in scoring_narratives:
                    nid = narr.get("narrative_id", "")
                    links_for_narr = self.link_repo.get_active_for_narrative(nid)
                    narr_token_links[nid] = [
                        lnk["token_id"] for lnk in links_for_narr
                    ]

                cluster_map = self.narrative_intel.cluster_narratives(
                    scoring_narratives, narr_token_links,
                )
                # Persist cluster_id on narratives
                for nid, cid in cluster_map.items():
                    self.narrative_repo.update_fields(nid, {"cluster_id": cid})
        except Exception as e:
            logger.error("pipeline_clustering_error", error=str(e))
            summary["errors"].append(f"clustering: {e}")

        # Step 3.7: Narrative competition — select winners per cluster group.
        # Persist competition_status and competition_rank on narratives.
        # Store full outcomes for dashboard visibility.
        competition_outcomes: list[dict] = []
        try:
            fresh_scoring = self.narrative_repo.get_for_scoring()
            if fresh_scoring:
                ranked = self.narrative_intel.select_narrative_winners(fresh_scoring)
                for n in ranked:
                    nid = n.get("narrative_id", "")
                    self.narrative_repo.update_fields(nid, {
                        "competition_status": n.get("competition_status"),
                        "competition_rank": n.get("competition_rank"),
                    })
                    competition_outcomes.append({
                        "narrative_id": nid,
                        "narrative_name": n.get("description", n.get("name")),
                        "state": n.get("state"),
                        "narrative_strength": n.get("narrative_strength"),
                        "velocity_state": n.get("velocity_state"),
                        "cluster_id": n.get("cluster_id"),
                        "competition_status": n.get("competition_status"),
                        "competition_rank": n.get("competition_rank"),
                        "suppression_reasons": n.get("suppression_reasons", []),
                        "winner_explanation": n.get("winner_explanation"),
                    })
                logger.info(
                    "narrative_competition_complete",
                    total=len(ranked),
                    winners=sum(
                        1 for n in ranked
                        if n.get("competition_status") in ("winner", "no_contest")
                    ),
                )
        except Exception as e:
            logger.error("pipeline_narrative_competition_error", error=str(e))
            summary["errors"].append(f"narrative_competition: {e}")

        summary["competition_outcomes"] = competition_outcomes

        # Step 4: Correlate tokens with narratives
        # Use scoring-eligible narratives for correlation (EMERGING, RISING, TRENDING)
        try:
            active_narratives = self.narrative_repo.get_for_scoring()
            tokens_to_correlate = self.token_repo.list_by_status("new", limit=200)

            links_created = 0
            for token in tokens_to_correlate:
                try:
                    links = self.correlator.correlate_token(token, active_narratives)
                    for link in links:
                        existing_links = self.link_repo.get_for_token(token["token_id"])
                        already_linked = any(
                            el.get("narrative_id") == link["narrative_id"]
                            for el in existing_links
                        )
                        if not already_linked:
                            self.link_repo.save(link)
                            links_created += 1

                    token_links = self.link_repo.get_for_token(token["token_id"])
                    if token_links:
                        self.token_repo.update_status(
                            token["token_id"], "linked", "narrative_correlated"
                        )
                except Exception as e:
                    logger.error("token_correlation_error",
                                 token_id=token.get("token_id"), error=str(e))
                    summary["errors"].append(f"correlate:{token.get('token_id')}: {e}")

            # OG resolution
            for narrative in active_narratives:
                try:
                    nid = narrative.get("narrative_id", narrative.get("id", ""))
                    namespace_links = self.link_repo.get_active_for_narrative(nid)
                    if len(namespace_links) > 1:
                        token_launch_times: dict[str, datetime] = {}
                        for link in namespace_links:
                            tok = self.token_repo.get_by_id(link["token_id"])
                            if tok and tok.get("launch_time"):
                                try:
                                    lt = datetime.fromisoformat(
                                        tok["launch_time"].replace("Z", "+00:00")
                                    )
                                    if lt.tzinfo is None:
                                        lt = lt.replace(tzinfo=timezone.utc)
                                    token_launch_times[link["token_id"]] = lt
                                except (ValueError, TypeError):
                                    pass
                        resolved = self.correlator.resolve_namespace(
                            namespace_links, token_launch_times
                        )
                        for updated_link in resolved:
                            self.link_repo.save(updated_link)
                except Exception as e:
                    logger.error("og_resolution_error",
                                 narrative_id=narrative.get("narrative_id"),
                                 error=str(e))
                    summary["errors"].append(f"og_resolve: {e}")

            summary["links_created"] = links_created
        except Exception as e:
            logger.error("pipeline_correlation_error", error=str(e))
            summary["errors"].append(f"correlation: {e}")

        # Step 5 & 6: Score linked tokens, apply quality gating & competition, classify alerts
        linked_tokens = self.token_repo.list_by_status("linked", limit=200)
        scored_count = 0
        quality_gated_count = 0

        # Collect all scored tokens per narrative for competition layer
        narrative_scored_tokens: dict[str, list[dict]] = {}

        for token in linked_tokens:
            token_links = self.link_repo.get_for_token(token["token_id"])
            for link in token_links:
                if link.get("status") != "active":
                    continue

                narrative = self.narrative_repo.get_by_id(link["narrative_id"])
                if narrative is None:
                    continue

                # Quality gate: skip narratives not meeting scoring eligibility
                if not self.narrative_intel.is_scoring_eligible(narrative):
                    reason = self.narrative_intel.get_rejection_reason(narrative)
                    logger.debug(
                        "narrative_quality_gate_blocked",
                        narrative_id=narrative.get("narrative_id"),
                        state=narrative.get("state"),
                        reason=reason,
                    )
                    quality_gated_count += 1
                    continue

                try:
                    snapshot = self.token_repo.get_latest_snapshot(token["token_id"])
                    chain_data = self._build_chain_data(token, snapshot)
                    narrative_data = self._build_narrative_data(narrative, link)
                    social_data = {}
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

                    # Collect for competition layer
                    nid = link["narrative_id"]
                    narrative_scored_tokens.setdefault(nid, []).append({
                        "scored": scored,
                        "token": token,
                        "narrative": narrative,
                        "link": link,
                    })

                except Exception as e:
                    logger.error(
                        "token_scoring_error",
                        token_id=token.get("token_id"),
                        link_id=link.get("link_id"),
                        error=str(e),
                    )
                    summary["errors"].append(
                        f"score:{token.get('token_id')}:{link.get('link_id')}: {e}"
                    )

            try:
                self.token_repo.update_status(
                    token["token_id"], "scored", "scoring_complete"
                )
            except Exception as e:
                logger.error("token_status_update_error",
                             token_id=token.get("token_id"), error=str(e))

        summary["tokens_scored"] = scored_count
        summary["quality_gated"] = quality_gated_count
        self._total_tokens_processed += scored_count

        # Step 5.5: Competition layer — strict winner-takes-all.
        # No fallback: only RISING+ narratives may produce alerts.
        # Only rank-1 token per narrative proceeds to alert classification.
        # All others are suppressed with structured reasons.
        suppressed_count = 0
        token_competition_outcomes: list[dict] = []

        for nid, items in narrative_scored_tokens.items():
            # Token competition: rank tokens within this narrative
            tokens_for_competition = [
                {
                    "token_id": item["token"]["token_id"],
                    "net_potential": item["scored"].get("net_potential", 0.0) or 0.0,
                    "_item": item,
                }
                for item in items
            ]

            ranked = self.narrative_intel.select_token_winners(tokens_for_competition)

            for entry in ranked:
                token_competition_outcomes.append({
                    "narrative_id": nid,
                    "token_id": entry.get("token_id"),
                    "token_name": entry["_item"]["token"].get("name"),
                    "net_potential": entry.get("net_potential"),
                    "token_competition_status": entry.get("token_competition_status"),
                    "suppression_reasons": entry.get("suppression_reasons", []),
                    "winner_explanation": entry.get("winner_explanation"),
                })

            for entry in ranked:
                item = entry["_item"]
                scored = item["scored"]
                token = item["token"]
                narrative = item["narrative"]
                link = item["link"]
                competition_status = entry.get("token_competition_status", "winner")
                suppression_reasons = entry.get("suppression_reasons", [])

                # Alert gating: narrative must be RISING+ (strict, no fallback)
                if not self.narrative_intel.is_alert_eligible(narrative):
                    narr_reasons = self.narrative_intel.get_suppression_reasons(narrative)
                    logger.info(
                        "alert_narrative_gate_failed",
                        token_id=token.get("token_id"),
                        narrative_id=narrative.get("narrative_id"),
                        narrative_state=narrative.get("state"),
                        suppression_reasons=[r["code"] for r in narr_reasons],
                    )
                    self._handle_rejection(
                        scored, token, narrative,
                        extra_reasons=narr_reasons,
                    )
                    suppressed_count += 1
                    continue

                # Strict winner-takes-all: only "winner" proceeds
                if competition_status != "winner":
                    logger.info(
                        "token_suppressed",
                        token_id=token.get("token_id"),
                        narrative_id=narrative.get("narrative_id"),
                        competition_status=competition_status,
                        suppression_reasons=[r["code"] for r in suppression_reasons],
                    )
                    self._handle_rejection(
                        scored, token, narrative,
                        extra_reasons=suppression_reasons,
                    )
                    suppressed_count += 1
                    continue

                # Step 6: Alert classification — only the single winner reaches here
                alert = self.alert_engine.process_scored_token(
                    scored_token=scored,
                    token=token,
                    narrative=narrative,
                    link=link,
                )

                if alert:
                    summary["alerts_created"] += 1
                    self._total_alerts_generated += 1

                    # Step 7: Deliver and persist delivery records
                    logs = await self.delivery.deliver_alert(alert)
                    for log in logs:
                        try:
                            self.alert_repo.save_delivery(log)
                        except Exception as e:
                            logger.error("delivery_log_persist_error", error=str(e))
                    summary["alerts_delivered"] += sum(
                        1 for l in logs if l.get("status") == "delivered"
                    )
                else:
                    self._handle_rejection(scored, token, narrative)

        summary["suppressed"] = suppressed_count
        summary["token_competition_outcomes"] = token_competition_outcomes

        # Step 8: Expire stale alerts and retire old ones
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            expired = self.alert_engine.check_expired_alerts()
            for exp_alert in expired:
                logger.info(
                    "alert_expired",
                    alert_id=exp_alert.get("alert_id"),
                    type=exp_alert.get("alert_type"),
                )
            summary["alerts_expired"] = len(expired)

            # Purge alerts older than retention window
            if self.settings is not None:
                retention_hours = self.settings.retired_alert_retention_hours
            else:
                retention_hours = 168  # 7 days default
            cutoff = datetime.now(timezone.utc) - timedelta(hours=retention_hours)
            purged_alerts = self.alert_repo.purge_old_retired(cutoff.isoformat())
            if purged_alerts:
                logger.info("old_alerts_purged", count=purged_alerts)

        except Exception as e:
            logger.error("pipeline_expiry_error", error=str(e))
            summary["errors"].append(f"expiry: {e}")

        # Step 9: Prune old data per retention policy (every cycle)
        try:
            if self.settings is not None:
                snap_hours = self.settings.chain_snapshot_retention_hours
                score_hours = self.settings.scored_token_retention_hours
            else:
                snap_hours = 48
                score_hours = 72

            snap_cutoff = datetime.now(timezone.utc) - timedelta(hours=snap_hours)
            score_cutoff = datetime.now(timezone.utc) - timedelta(hours=score_hours)

            pruned_snaps = self.token_repo.prune_old_snapshots(snap_cutoff.isoformat())
            pruned_scores = self.scoring_repo.prune_old_scored_tokens(score_cutoff.isoformat())

            # Prune rejected candidates older than 48h (they are diagnostic data,
            # not calibration data; compound PK keeps one row per pair anyway).
            rejected_cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
            pruned_rejected = self.rejected_repo.prune_old(rejected_cutoff.isoformat())

            total_pruned = pruned_snaps + pruned_scores + pruned_rejected
            if total_pruned:
                logger.info("data_pruned",
                            snapshots=pruned_snaps, scored_tokens=pruned_scores,
                            rejected_candidates=pruned_rejected)
            summary["rows_pruned"] = total_pruned
        except Exception as e:
            logger.error("pipeline_pruning_error", error=str(e))
            summary["errors"].append(f"pruning: {e}")

        elapsed = (datetime.now(timezone.utc) - cycle_start).total_seconds()
        summary["elapsed_seconds"] = round(elapsed, 2)
        logger.info("pipeline_cycle_complete", **summary)

        return summary

    def get_stats(self) -> dict:
        """Return pipeline statistics."""
        db_size_mb = round(self.db.get_size_bytes() / (1024 * 1024), 2)
        return {
            "cycles_completed": self._cycle_count,
            "total_tokens_processed": self._total_tokens_processed,
            "total_alerts_generated": self._total_alerts_generated,
            "source_health": self.ingestion.get_source_health(),
            "active_alerts": len(self.alert_repo.get_active()),
            "open_source_gaps": len(self.gap_repo.get_open_gaps()),
            "db_size_mb": db_size_mb,
        }

    # --- Data building helpers ---

    def _handle_rejection(
        self,
        scored: dict,
        token: dict,
        narrative: dict,
        extra_reasons: list[dict] | None = None,
    ) -> None:
        """Log and persist a structured rejection record for a token classified as ignore.

        Called when a token is suppressed by competition, narrative gating,
        or alert classification.  Produces a per-tier breakdown of which
        thresholds were not met so the operator can tune thresholds.

        Parameters
        ----------
        extra_reasons
            Additional structured suppression reasons (e.g., from competition
            layer or narrative gating) to merge into the rejection record.
        """
        net_potential = scored.get("net_potential", 0.0) or 0.0
        p_potential = scored.get("p_potential", 0.0) or 0.0
        p_failure = scored.get("p_failure", 0.0) or 0.0
        confidence = scored.get("confidence_score", 0.0) or 0.0
        risk_flags = scored.get("risk_flags") or []
        data_gaps = scored.get("data_gaps") or []
        narrative_state = narrative.get("state", "WEAK")
        watch_min = self.alert_engine.thresholds.watch_min_net_potential

        reasons = explain_rejection(
            net_potential=net_potential,
            p_potential=p_potential,
            p_failure=p_failure,
            confidence=confidence,
            risk_flags=risk_flags,
            narrative_state=narrative_state,
            data_gaps=data_gaps,
            thresholds=self.alert_engine.thresholds,
        )

        # Merge suppression reasons from competition/gating layer
        if extra_reasons:
            reasons.extend(extra_reasons)

        watch_gap = round(watch_min - net_potential, 4)

        # Structured log — one line per rejected token, visible in pipeline output
        logger.info(
            "token_rejected_no_alert",
            token_id=token.get("token_id"),
            token_name=token.get("name"),
            token_symbol=token.get("symbol"),
            narrative_id=narrative.get("narrative_id"),
            narrative_name=narrative.get("description", narrative.get("name")),
            narrative_state=narrative_state,
            net_potential=net_potential,
            p_potential=p_potential,
            p_failure=p_failure,
            confidence=confidence,
            watch_gap=watch_gap,
            rejection_reasons=[r["code"] for r in reasons],
            data_gaps=data_gaps,
        )

        # Persist to rejected_candidates table for dashboard display
        try:
            candidate = {
                "token_id": token["token_id"],
                "narrative_id": narrative["narrative_id"],
                "token_name": token.get("name"),
                "token_symbol": token.get("symbol"),
                "narrative_name": narrative.get("description", narrative.get("name")),
                "score_id": scored.get("score_id"),
                "alert_type": "ignore",
                "net_potential": net_potential,
                "p_potential": p_potential,
                "p_failure": p_failure,
                "confidence_score": confidence,
                "watch_gap": watch_gap,
                "rejection_reasons": reasons,
                "dimension_scores": {
                    "narrative_relevance": scored.get("narrative_relevance"),
                    "og_score": scored.get("og_score"),
                    "rug_risk": scored.get("rug_risk"),
                    "momentum_quality": scored.get("momentum_quality"),
                    "attention_strength": scored.get("attention_strength"),
                    "timing_quality": scored.get("timing_quality"),
                },
                "risk_flags": risk_flags,
                "data_gaps": data_gaps,
                "rejected_at": datetime.now(timezone.utc).isoformat(),
            }
            self.rejected_repo.save(candidate)
        except Exception as e:
            logger.error("rejected_candidate_persist_error", error=str(e))

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
            "state": narrative.get("state", "WEAK"),
            "attention_score": narrative.get("attention_score", 0.5),
            "narrative_velocity": narrative.get("narrative_velocity", 0.0),
            "narrative_strength": narrative.get("narrative_strength"),
            "velocity_state": narrative.get("velocity_state"),
        }

    def _build_link_data(self, link: dict) -> dict:
        """Build link_data dict for the scorer."""
        return {
            "og_rank": link.get("og_rank"),
            "og_score": link.get("og_score"),
            "cross_source_mentions": 0,
            "match_method": link.get("match_method", "exact"),
        }
