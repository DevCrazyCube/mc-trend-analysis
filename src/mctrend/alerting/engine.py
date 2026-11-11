"""Alert engine: creates, updates, retires alerts based on scored tokens."""

import uuid
from datetime import datetime, timedelta, timezone

from mctrend.alerting.classifier import AlertThresholds, classify_alert
from mctrend.alerting.reasoning import generate_reasoning

# Alert expiry windows in minutes (configurable defaults).
DEFAULT_EXPIRY_MINUTES: dict[str, int] = {
    "possible_entry": 60,
    "high_potential_watch": 120,
    "take_profit_watch": 30,
    "verify": 120,
    "watch": 240,
    "exit_risk": 15,
    "discard": 0,
}

# Re-evaluation triggers by alert type (configurable defaults).
DEFAULT_RE_EVAL_TRIGGERS: dict[str, list[str]] = {
    "possible_entry": [
        "liquidity_drop_critical",
        "attention_decay_50pct",
        "holder_dump",
        "narrative_dead",
    ],
    "high_potential_watch": [
        "liquidity_drop_critical",
        "attention_decay_50pct",
        "holder_dump",
    ],
    "watch": [
        "liquidity_drop_critical",
        "narrative_dead",
    ],
    "exit_risk": [
        "liquidity_drop_critical",
        "deployer_exit",
    ],
}


class AlertEngine:
    """Core alert engine: classifies scored tokens and manages alert lifecycle."""

    def __init__(
        self,
        alert_repo,
        thresholds: AlertThresholds | None = None,
        expiry_minutes: dict[str, int] | None = None,
        history_max_entries: int = 50,
    ):
        """
        Parameters
        ----------
        alert_repo:
            AlertRepository instance (must have save, get_active_for_token,
            get_expired, retire methods).
        thresholds:
            Optional AlertThresholds override; uses defaults when None.
        expiry_minutes:
            Optional per-type expiry overrides; uses DEFAULT_EXPIRY_MINUTES
            when None.
        history_max_entries:
            Maximum number of lifecycle history entries to retain per alert.
        """
        self.alert_repo = alert_repo
        self.thresholds = thresholds if thresholds is not None else AlertThresholds()
        self.expiry_minutes = (
            expiry_minutes if expiry_minutes is not None else dict(DEFAULT_EXPIRY_MINUTES)
        )
        self.history_max_entries = history_max_entries

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_scored_token(
        self,
        scored_token: dict,
        token: dict,
        narrative: dict,
        link: dict,
    ) -> dict | None:
        """
        Main entry point. Takes a scored token and produces/updates an alert.

        Parameters
        ----------
        scored_token:
            Dict with score_id, dimensions (dict of 6 scores), probabilities
            (dict with p_potential, p_failure, net_potential, confidence),
            risk_flags, data_gaps, dimension_details (optional), scored_at.
        token:
            Dict with token_id, address, name, symbol.
        narrative:
            Dict with narrative_id, description (or name), state.
        link:
            Dict with link_id.

        Returns
        -------
        Alert dict if one was created/updated, None if ignored.
        """
        # 1. Extract scores (flat layout from ScoringAggregator)
        net_potential = scored_token.get("net_potential", 0.0)
        p_potential = scored_token.get("p_potential", 0.0)
        p_failure = scored_token.get("p_failure", 0.0)
        confidence = scored_token.get("confidence_score", 0.0)
        dimension_scores = {
            "narrative_relevance": scored_token.get("narrative_relevance"),
            "og_score": scored_token.get("og_score"),
            "rug_risk": scored_token.get("rug_risk"),
            "momentum_quality": scored_token.get("momentum_quality"),
            "attention_strength": scored_token.get("attention_strength"),
            "timing_quality": scored_token.get("timing_quality"),
        }
        risk_flags = scored_token.get("risk_flags", [])
        data_gaps = scored_token.get("data_gaps", [])
        dimension_details = scored_token.get("dimension_details", None)
        narrative_state = narrative.get("state", "EMERGING")

        # 2. Check for existing active alert
        token_id = token["token_id"]
        existing_alert = self.alert_repo.get_active_for_token(token_id)

        has_prior_alert = existing_alert is not None
        prior_alert_type = existing_alert["alert_type"] if existing_alert else None

        # 3. Classify
        alert_type = classify_alert(
            net_potential=net_potential,
            p_potential=p_potential,
            p_failure=p_failure,
            confidence=confidence,
            risk_flags=risk_flags,
            narrative_state=narrative_state,
            has_prior_alert=has_prior_alert,
            prior_alert_type=prior_alert_type,
            thresholds=self.thresholds,
        )

        # 4. If ignore and no prior alert: return None
        if alert_type == "ignore" and not has_prior_alert:
            return None

        # 5. Generate reasoning
        narrative_name = narrative.get("description", narrative.get("name", "Unknown"))
        reasoning = generate_reasoning(
            alert_type=alert_type,
            token_name=token.get("name", "Unknown"),
            token_symbol=token.get("symbol", "???"),
            narrative_name=narrative_name,
            net_potential=net_potential,
            p_potential=p_potential,
            p_failure=p_failure,
            confidence=confidence,
            dimension_scores=dimension_scores,
            risk_flags=risk_flags,
            data_gaps=data_gaps,
            narrative_state=narrative_state,
            dimension_details=dimension_details,
        )

        # 6. Create or update alert
        if existing_alert is not None:
            # If the new classification is ignore for an existing alert, retire it
            if alert_type == "ignore":
                self.retire_alert(
                    existing_alert["alert_id"],
                    reason="Re-classified as ignore; below all thresholds",
                )
                return existing_alert

            # If discard, retire the existing alert
            if alert_type == "discard":
                alert = self._update_alert(existing_alert, alert_type, scored_token, reasoning)
                self.alert_repo.save(alert)
                self.retire_alert(
                    alert["alert_id"],
                    reason="Re-classified as discard; strong failure signals",
                )
                return alert

            alert = self._update_alert(existing_alert, alert_type, scored_token, reasoning)
        else:
            # Discard with no prior alert: still create and immediately retire
            if alert_type == "discard":
                alert = self._create_alert(
                    alert_type, scored_token, token, narrative, link, reasoning
                )
                self.alert_repo.save(alert)
                self.retire_alert(
                    alert["alert_id"],
                    reason="Classified as discard on initial evaluation",
                )
                return alert

            alert = self._create_alert(
                alert_type, scored_token, token, narrative, link, reasoning
            )

        # 7. Save to repo
        self.alert_repo.save(alert)

        # 8. Return alert dict
        return alert

    def check_expired_alerts(self, now: datetime | None = None) -> list[dict]:
        """Return list of alerts that have expired and need re-evaluation.

        Parameters
        ----------
        now:
            Current time. Defaults to utcnow if not provided.

        Returns
        -------
        List of expired alert dicts.
        """
        if now is None:
            now = datetime.now(timezone.utc)

        now_iso = now.isoformat()
        return self.alert_repo.get_expired(now_iso)

    def retire_alert(self, alert_id: str, reason: str) -> None:
        """Retire an alert with a reason and current timestamp."""
        retired_at = datetime.now(timezone.utc).isoformat()
        self.alert_repo.retire(alert_id, reason, retired_at)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _create_alert(
        self,
        alert_type: str,
        scored_token: dict,
        token: dict,
        narrative: dict,
        link: dict,
        reasoning: str,
    ) -> dict:
        """Create a new alert dict."""
        now = datetime.now(timezone.utc)
        expiry_min = self.expiry_minutes.get(alert_type, 120)
        expires_at = now + timedelta(minutes=expiry_min)

        alert = {
            "alert_id": str(uuid.uuid4()),
            "token_id": token["token_id"],
            "token_address": token.get("address", ""),
            "token_name": token.get("name", "Unknown"),
            "token_symbol": token.get("symbol", "???"),
            "narrative_id": narrative["narrative_id"],
            "narrative_name": narrative.get(
                "description", narrative.get("name", "Unknown")
            ),
            "link_id": link["link_id"],
            "score_id": scored_token.get("score_id", ""),
            "alert_type": alert_type,
            "net_potential": scored_token.get("net_potential", 0.0),
            "p_potential": scored_token.get("p_potential", 0.0),
            "p_failure": scored_token.get("p_failure", 0.0),
            "confidence_score": scored_token.get("confidence_score", 0.0),
            "dimension_scores": {
                "narrative_relevance": scored_token.get("narrative_relevance"),
                "og_score": scored_token.get("og_score"),
                "rug_risk": scored_token.get("rug_risk"),
                "momentum_quality": scored_token.get("momentum_quality"),
                "attention_strength": scored_token.get("attention_strength"),
                "timing_quality": scored_token.get("timing_quality"),
            },
            "risk_flags": scored_token.get("risk_flags", []),
            "reasoning": reasoning,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "re_eval_triggers": DEFAULT_RE_EVAL_TRIGGERS.get(alert_type, []),
            "status": "ACTIVE",
            "history": [],
        }

        return alert

    def _update_alert(
        self,
        existing_alert: dict,
        new_type: str,
        scored_token: dict,
        reasoning: str,
    ) -> dict:
        """Update existing alert with new classification. Append to history."""
        now = datetime.now(timezone.utc)

        # Build a history entry capturing the previous state
        history_entry = {
            "timestamp": now.isoformat(),
            "previous_type": existing_alert["alert_type"],
            "new_type": new_type,
            "previous_scores": {
                "net_potential": existing_alert.get("net_potential"),
                "p_potential": existing_alert.get("p_potential"),
                "p_failure": existing_alert.get("p_failure"),
                "confidence_score": existing_alert.get("confidence_score"),
            },
            "new_scores": {
                "net_potential": scored_token.get("net_potential", 0.0),
                "p_potential": scored_token.get("p_potential", 0.0),
                "p_failure": scored_token.get("p_failure", 0.0),
                "confidence_score": scored_token.get("confidence_score", 0.0),
            },
            "change_reason": _describe_change(
                existing_alert["alert_type"], new_type
            ),
        }

        # Copy existing alert and update fields; cap history to avoid unbounded growth
        history = list(existing_alert.get("history", []))
        history.append(history_entry)
        if len(history) > self.history_max_entries:
            history = history[-self.history_max_entries:]

        # Compute new expiry from now
        expiry_min = self.expiry_minutes.get(new_type, 120)
        expires_at = now + timedelta(minutes=expiry_min)

        updated_alert = dict(existing_alert)
        updated_alert.update(
            {
                "alert_type": new_type,
                "net_potential": scored_token.get("net_potential", 0.0),
                "p_potential": scored_token.get("p_potential", 0.0),
                "p_failure": scored_token.get("p_failure", 0.0),
                "confidence_score": scored_token.get("confidence_score", 0.0),
                "dimension_scores": {
                    "narrative_relevance": scored_token.get("narrative_relevance"),
                    "og_score": scored_token.get("og_score"),
                    "rug_risk": scored_token.get("rug_risk"),
                    "momentum_quality": scored_token.get("momentum_quality"),
                    "attention_strength": scored_token.get("attention_strength"),
                    "timing_quality": scored_token.get("timing_quality"),
                },
                "risk_flags": scored_token.get("risk_flags", []),
                "reasoning": reasoning,
                "score_id": scored_token.get("score_id", ""),
                "updated_at": now.isoformat(),
                "expires_at": expires_at.isoformat(),
                "re_eval_triggers": DEFAULT_RE_EVAL_TRIGGERS.get(new_type, []),
                "history": history,
            }
        )

        return updated_alert


def _describe_change(old_type: str, new_type: str) -> str:
    """Generate a short human-readable description of an alert type transition."""
    if old_type == new_type:
        return "Score update (type unchanged)"

    from mctrend.alerting.classifier import ALERT_TIERS

    old_tier = ALERT_TIERS.get(old_type, 6)
    new_tier = ALERT_TIERS.get(new_type, 6)

    if new_tier < old_tier:
        return f"Upgraded from {old_type} to {new_type}"
    elif new_tier > old_tier:
        return f"Downgraded from {old_type} to {new_type}"
    else:
        return f"Lateral change from {old_type} to {new_type}"
