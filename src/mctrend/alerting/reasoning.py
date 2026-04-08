"""Generate human-readable reasoning strings for alerts."""

# Map risk flags to human-readable descriptions
RISK_FLAG_DESCRIPTIONS: dict[str, str] = {
    "CRITICAL_RUG_RISK": "Critical rug risk signals detected",
    "HIGH_HOLDER_CONCENTRATION": "Top wallets hold majority of supply",
    "WALLET_CLUSTERING": "Wallet clustering detected among holders",
    "NEW_DEPLOYER": "Token deployer has no established history",
    "KNOWN_BAD_DEPLOYER": "Deployer associated with previous rug pulls",
    "UNLOCKED_LIQUIDITY": "Liquidity pool is not locked",
    "LOW_LIQUIDITY": "Very low liquidity available",
    "MINT_AUTHORITY_ACTIVE": "Mint authority has not been renounced",
    "FREEZE_AUTHORITY_ACTIVE": "Freeze authority is enabled",
    "SUSPICIOUS_VOLUME": "Trading volume shows suspicious patterns",
    "WASH_TRADE_PATTERN": "Potential wash trading detected",
    "LOW_CONFIDENCE": "Limited data available for evaluation",
    "NARRATIVE_AMBIGUOUS": "Multiple possible narrative matches",
    "COPYCAT_LIKELY": "Token is likely a copycat, not the original",
    "NARRATIVE_DECLINING": "Narrative attention is declining",
    "TIMING_LATE": "Late in the narrative lifecycle",
    "DATA_GAP": "Missing data for one or more scoring dimensions",
    "FREEZE_AUTHORITY_ACTIVE_AND_MINT_AUTHORITY_ACTIVE": (
        "Both freeze and mint authority are still active"
    ),
}

# Dimension names ordered by their contribution to P_potential (positive signal).
# rug_risk is inverted (higher = worse), so it contributes as a negative signal.
_POSITIVE_DIMENSIONS = [
    "narrative_relevance",
    "og_score",
    "momentum_quality",
    "attention_strength",
    "timing_quality",
]

_NEGATIVE_DIMENSIONS = [
    "rug_risk",
]

# Human-readable labels for each dimension key.
_DIMENSION_LABELS: dict[str, str] = {
    "narrative_relevance": "narrative match",
    "og_score": "OG authenticity",
    "rug_risk": "rug risk",
    "momentum_quality": "momentum quality",
    "attention_strength": "attention strength",
    "timing_quality": "timing quality",
}


def get_top_signals(
    dimension_details: dict, positive: bool = True, n: int = 2
) -> list[str]:
    """Extract top N positive or negative signals from dimension details.

    *dimension_details* maps dimension names to dicts that may contain a
    ``score`` (float) and optionally a ``description`` (str).

    When *positive* is True, returns the dimensions with the highest scores
    (excluding rug_risk which is inverted). When False, returns dimensions
    contributing most to risk (high rug_risk or low positive dimensions).
    """
    if not dimension_details:
        return []

    scored_items: list[tuple[str, float, str]] = []

    for dim_name, detail in dimension_details.items():
        if not isinstance(detail, dict):
            continue
        score = detail.get("score")
        if score is None:
            continue
        description = detail.get("description", "")
        label = _DIMENSION_LABELS.get(dim_name, dim_name)

        if positive:
            # For positive signals: high scores on positive dimensions
            if dim_name in _POSITIVE_DIMENSIONS:
                scored_items.append((label, score, description))
        else:
            # For negative signals: high rug_risk or low positive dimensions
            if dim_name in _NEGATIVE_DIMENSIONS:
                scored_items.append((label, score, description))
            elif dim_name in _POSITIVE_DIMENSIONS:
                # Invert: low positive score = negative signal
                scored_items.append((label, 1.0 - score, description))

    # Sort descending by score value
    scored_items.sort(key=lambda x: x[1], reverse=True)

    results: list[str] = []
    for label, score, description in scored_items[:n]:
        if description:
            results.append(f"{label} ({score:.2f}): {description}")
        else:
            results.append(f"{label} ({score:.2f})")

    return results


def get_confidence_note(confidence: float, data_gaps: list[str]) -> str:
    """Generate a brief confidence explanation."""
    if confidence >= 0.80:
        quality = "high"
    elif confidence >= 0.60:
        quality = "moderate"
    elif confidence >= 0.40:
        quality = "low"
    else:
        quality = "very low"

    note = f"{confidence:.2f} ({quality} data quality)"

    if data_gaps:
        gap_text = ", ".join(data_gaps[:3])
        remaining = len(data_gaps) - 3
        if remaining > 0:
            gap_text += f" and {remaining} more"
        note += f" -- missing: {gap_text}"
    else:
        note += " -- all data sources available"

    return note


def get_window_estimate(timing_quality: float, narrative_state: str) -> str:
    """Estimate remaining opportunity window based on timing and narrative state.

    This produces a qualitative estimate, not a precise prediction.
    """
    state_lower = narrative_state.upper()

    if state_lower == "DEAD":
        return "Narrative is dead; no remaining window"

    if state_lower == "DECLINING":
        if timing_quality >= 0.50:
            return "Narrative declining but some window may remain (1-2 hours estimated)"
        return "Narrative declining with limited remaining window"

    if state_lower == "PEAKING":
        if timing_quality >= 0.70:
            return "Narrative peaking with moderate window (2-4 hours estimated)"
        elif timing_quality >= 0.40:
            return "Narrative peaking, window narrowing (1-3 hours estimated)"
        else:
            return "Narrative peaking, window likely closing soon"

    # EMERGING or similar early states
    if timing_quality >= 0.80:
        return f"Narrative {state_lower.lower()} with substantial window (4-8 hours estimated)"
    elif timing_quality >= 0.60:
        return (
            f"Narrative {state_lower.lower()} with moderate window "
            f"(2-5 hours estimated)"
        )
    elif timing_quality >= 0.40:
        return (
            f"Narrative {state_lower.lower()} but timing quality is marginal "
            f"(1-3 hours estimated)"
        )
    else:
        return (
            f"Narrative {state_lower.lower()} but late entry; "
            f"window may be limited"
        )


# Human-readable alert type labels used in the reasoning header.
_ALERT_TYPE_LABELS: dict[str, str] = {
    "possible_entry": "POSSIBLE ENTRY",
    "high_potential_watch": "HIGH-POTENTIAL WATCH",
    "take_profit_watch": "TAKE-PROFIT WATCH",
    "verify": "VERIFY",
    "watch": "WATCH",
    "exit_risk": "EXIT-RISK",
    "discard": "DISCARD",
    "ignore": "IGNORE",
}


def generate_reasoning(
    alert_type: str,
    token_name: str,
    token_symbol: str,
    narrative_name: str,
    net_potential: float,
    p_potential: float,
    p_failure: float,
    confidence: float,
    dimension_scores: dict,
    risk_flags: list[str],
    data_gaps: list[str],
    narrative_state: str,
    dimension_details: dict | None = None,
) -> str:
    """
    Generate a complete reasoning string for an alert.

    Format follows the template from docs/alerting/alert-engine.md:

        [Alert Type] - $[Symbol] ([Name]) linked to "[Narrative Name]"

        Opportunity signal: net_potential [X], P_potential [X] driven by [top signals].
        Risk signal: P_failure [X] due to [top risk factors].
        Confidence: [X] -- [brief note on data quality/gaps].

        Key risk flags: [list of active risk flags].
        Window estimate: [qualitative window estimate].
    """
    details = dimension_details if dimension_details is not None else {}

    # -- Header line -------------------------------------------------------
    type_label = _ALERT_TYPE_LABELS.get(alert_type, alert_type.upper())
    header = f"{type_label} -- ${token_symbol} ({token_name}) linked to \"{narrative_name}\""

    # -- Opportunity signal line -------------------------------------------
    top_positive = get_top_signals(details, positive=True, n=3)
    if top_positive:
        drivers = "; ".join(top_positive)
        opportunity_line = (
            f"Opportunity signal: net_potential {net_potential:.2f}, "
            f"P_potential {p_potential:.2f} driven by {drivers}. "
            f"Narrative is in {narrative_state} state."
        )
    else:
        # Fallback when no dimension_details provided: use raw dimension_scores
        top_dims = _top_dimensions_from_scores(dimension_scores, positive=True, n=3)
        if top_dims:
            drivers = "; ".join(top_dims)
            opportunity_line = (
                f"Opportunity signal: net_potential {net_potential:.2f}, "
                f"P_potential {p_potential:.2f} driven by {drivers}. "
                f"Narrative is in {narrative_state} state."
            )
        else:
            opportunity_line = (
                f"Opportunity signal: net_potential {net_potential:.2f}, "
                f"P_potential {p_potential:.2f}. "
                f"Narrative is in {narrative_state} state."
            )

    # -- Risk signal line --------------------------------------------------
    top_negative = get_top_signals(details, positive=False, n=2)
    if top_negative:
        risk_factors = "; ".join(top_negative)
        risk_line = f"Risk signal: P_failure {p_failure:.2f} due to {risk_factors}."
    else:
        top_risk_dims = _top_dimensions_from_scores(dimension_scores, positive=False, n=2)
        if top_risk_dims:
            risk_factors = "; ".join(top_risk_dims)
            risk_line = f"Risk signal: P_failure {p_failure:.2f} due to {risk_factors}."
        else:
            risk_line = f"Risk signal: P_failure {p_failure:.2f}."

    # -- Confidence line ---------------------------------------------------
    confidence_line = f"Confidence: {get_confidence_note(confidence, data_gaps)}"

    # -- Risk flags line ---------------------------------------------------
    if risk_flags:
        flag_descriptions = []
        for flag in risk_flags:
            desc = RISK_FLAG_DESCRIPTIONS.get(flag, flag)
            flag_descriptions.append(f"{flag}: {desc}")
        risk_flags_line = f"Key risk flags: {'; '.join(flag_descriptions)}."
    else:
        risk_flags_line = "Key risk flags: None."

    # -- Window estimate line ----------------------------------------------
    timing_quality = dimension_scores.get("timing_quality", 0.5)
    window_line = f"Window estimate: {get_window_estimate(timing_quality, narrative_state)}"

    # -- Assemble ----------------------------------------------------------
    parts = [
        header,
        "",
        opportunity_line,
        risk_line,
        confidence_line,
        "",
        risk_flags_line,
        window_line,
    ]

    return "\n".join(parts)


def _top_dimensions_from_scores(
    dimension_scores: dict, positive: bool = True, n: int = 2
) -> list[str]:
    """Fallback: extract top dimension names/scores when dimension_details is absent."""
    if not dimension_scores:
        return []

    items: list[tuple[str, float]] = []
    for dim_name, score in dimension_scores.items():
        if not isinstance(score, (int, float)):
            continue
        label = _DIMENSION_LABELS.get(dim_name, dim_name)
        if positive:
            if dim_name in _POSITIVE_DIMENSIONS:
                items.append((label, float(score)))
        else:
            if dim_name in _NEGATIVE_DIMENSIONS:
                items.append((label, float(score)))
            elif dim_name in _POSITIVE_DIMENSIONS:
                items.append((label, 1.0 - float(score)))

    items.sort(key=lambda x: x[1], reverse=True)
    return [f"{label} ({score:.2f})" for label, score in items[:n]]
