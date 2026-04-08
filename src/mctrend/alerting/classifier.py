"""Classify scored tokens into alert types based on thresholds."""

from dataclasses import dataclass, field


@dataclass
class AlertThresholds:
    """All configurable thresholds for alert classification."""

    # possible_entry
    pe_min_net_potential: float = 0.60
    pe_max_p_failure: float = 0.30
    pe_min_confidence: float = 0.65
    # high_potential_watch
    hpw_min_net_potential: float = 0.45
    hpw_max_p_failure: float = 0.50
    hpw_min_confidence: float = 0.55
    # verify
    verify_min_net_potential: float = 0.35
    verify_max_confidence: float = 0.55  # verify is for LOW confidence
    # watch
    watch_min_net_potential: float = 0.25
    # exit_risk
    exit_risk_min_p_failure: float = 0.65
    # discard
    discard_min_p_failure: float = 0.80
    discard_max_net_potential: float = 0.10
    # Critical risk flags that block possible_entry
    blocking_flags: tuple = ("CRITICAL_RUG_RISK", "FREEZE_AUTHORITY_ACTIVE_AND_MINT_AUTHORITY_ACTIVE")
    # Flags that force discard
    discard_flags: tuple = ("KNOWN_BAD_DEPLOYER",)


# Ordered tiers from highest opportunity to lowest, used for comparisons.
ALERT_TIERS: dict[str, int] = {
    "possible_entry": 1,
    "high_potential_watch": 2,
    "take_profit_watch": 2,
    "verify": 3,
    "watch": 3,
    "exit_risk": 4,
    "discard": 5,
    "ignore": 6,
}

# The set of "high tier" prior alert types that qualify a token for take_profit_watch.
_HIGH_TIER_TYPES = {"possible_entry", "high_potential_watch"}

# Narrative states considered active enough for the top alert tiers.
_ACTIVE_NARRATIVE_STATES = {"EMERGING", "PEAKING"}

# Narrative states valid for take_profit_watch.
_TAKE_PROFIT_NARRATIVE_STATES = {"PEAKING", "DECLINING"}


def explain_rejection(
    net_potential: float,
    p_potential: float,
    p_failure: float,
    confidence: float,
    risk_flags: list[str],
    narrative_state: str = "EMERGING",
    data_gaps: list[str] | None = None,
    thresholds: AlertThresholds | None = None,
) -> list[dict]:
    """
    Return a structured list of reasons why a scored token did not reach each
    alert tier.  Intended for diagnostic logging and the dashboard rejection view.

    Each entry is a dict:
      code       — machine-readable reason code
      tier       — the alert tier this reason blocked
      actual     — the actual value (float or str; None for flag-based reasons)
      threshold  — the required threshold (float or str; None for flag-based)
      gap        — how far away from meeting the condition (positive = needs to
                   increase; None for non-numeric reasons)

    Only reasons that are actually failing are included.  A token that easily
    passes a tier will not generate reasons for that tier.
    """
    if thresholds is None:
        thresholds = AlertThresholds()

    reasons: list[dict] = []

    # ------------------------------------------------------------------
    # Flag-based blockers (always shown when present)
    # ------------------------------------------------------------------
    for flag in risk_flags:
        if flag in thresholds.discard_flags:
            reasons.append({
                "code": "discard_flag_active",
                "tier": "all",
                "actual": flag,
                "threshold": None,
                "gap": None,
            })

    blocking_flags_present = [f for f in risk_flags if f in thresholds.blocking_flags]
    if blocking_flags_present:
        reasons.append({
            "code": "blocking_flag_caps_at_verify",
            "tier": "possible_entry|high_potential_watch",
            "actual": ",".join(blocking_flags_present),
            "threshold": None,
            "gap": None,
        })

    # ------------------------------------------------------------------
    # Missing enrichment (data gaps)
    # ------------------------------------------------------------------
    _ENRICHMENT_GAPS = {
        "holder_concentration", "liquidity_data", "wallet_clustering",
        "deployer_history", "contract_authorities",
    }
    for gap in (data_gaps or []):
        if gap in _ENRICHMENT_GAPS:
            reasons.append({
                "code": "missing_required_enrichment",
                "tier": "rug_risk_dimension",
                "actual": gap,
                "threshold": None,
                "gap": None,
            })

    # ------------------------------------------------------------------
    # watch tier (net_potential >= 0.25)
    # ------------------------------------------------------------------
    if net_potential < thresholds.watch_min_net_potential:
        reasons.append({
            "code": "net_potential_below_watch",
            "tier": "watch",
            "actual": round(net_potential, 4),
            "threshold": thresholds.watch_min_net_potential,
            "gap": round(thresholds.watch_min_net_potential - net_potential, 4),
        })

    # ------------------------------------------------------------------
    # verify tier (net_potential >= 0.35 AND confidence < 0.55)
    # ------------------------------------------------------------------
    if net_potential < thresholds.verify_min_net_potential:
        reasons.append({
            "code": "net_potential_below_verify",
            "tier": "verify",
            "actual": round(net_potential, 4),
            "threshold": thresholds.verify_min_net_potential,
            "gap": round(thresholds.verify_min_net_potential - net_potential, 4),
        })

    # ------------------------------------------------------------------
    # high_potential_watch tier
    # ------------------------------------------------------------------
    if net_potential < thresholds.hpw_min_net_potential:
        reasons.append({
            "code": "net_potential_below_hpw",
            "tier": "high_potential_watch",
            "actual": round(net_potential, 4),
            "threshold": thresholds.hpw_min_net_potential,
            "gap": round(thresholds.hpw_min_net_potential - net_potential, 4),
        })
    if p_failure >= thresholds.hpw_max_p_failure:
        reasons.append({
            "code": "p_failure_too_high_for_hpw",
            "tier": "high_potential_watch",
            "actual": round(p_failure, 4),
            "threshold": thresholds.hpw_max_p_failure,
            "gap": round(p_failure - thresholds.hpw_max_p_failure, 4),
        })
    if confidence < thresholds.hpw_min_confidence:
        reasons.append({
            "code": "confidence_below_hpw_floor",
            "tier": "high_potential_watch",
            "actual": round(confidence, 4),
            "threshold": thresholds.hpw_min_confidence,
            "gap": round(thresholds.hpw_min_confidence - confidence, 4),
        })
    if narrative_state not in _ACTIVE_NARRATIVE_STATES:
        reasons.append({
            "code": "narrative_state_not_active",
            "tier": "high_potential_watch|possible_entry",
            "actual": narrative_state,
            "threshold": "|".join(sorted(_ACTIVE_NARRATIVE_STATES)),
            "gap": None,
        })

    # ------------------------------------------------------------------
    # possible_entry tier
    # ------------------------------------------------------------------
    if net_potential < thresholds.pe_min_net_potential:
        reasons.append({
            "code": "net_potential_below_pe",
            "tier": "possible_entry",
            "actual": round(net_potential, 4),
            "threshold": thresholds.pe_min_net_potential,
            "gap": round(thresholds.pe_min_net_potential - net_potential, 4),
        })
    if p_failure >= thresholds.pe_max_p_failure:
        reasons.append({
            "code": "p_failure_too_high_for_pe",
            "tier": "possible_entry",
            "actual": round(p_failure, 4),
            "threshold": thresholds.pe_max_p_failure,
            "gap": round(p_failure - thresholds.pe_max_p_failure, 4),
        })
    if confidence < thresholds.pe_min_confidence:
        reasons.append({
            "code": "confidence_below_pe_floor",
            "tier": "possible_entry",
            "actual": round(confidence, 4),
            "threshold": thresholds.pe_min_confidence,
            "gap": round(thresholds.pe_min_confidence - confidence, 4),
        })

    return reasons


def classify_alert(
    net_potential: float,
    p_potential: float,
    p_failure: float,
    confidence: float,
    risk_flags: list[str],
    narrative_state: str = "EMERGING",
    has_prior_alert: bool = False,
    prior_alert_type: str | None = None,
    thresholds: AlertThresholds | None = None,
) -> str:
    """
    Classify a scored token into an alert type.

    Returns one of: "possible_entry", "high_potential_watch", "take_profit_watch",
                    "verify", "watch", "exit_risk", "discard", "ignore"

    Rules (applied in strict order):
    1. Check discard flags first -> discard
    2. Check discard thresholds -> discard
    3. Check exit_risk (only if has_prior_alert and p_failure >= threshold) -> exit_risk
    4. Check blocking flags -> cap at verify
    5. Check possible_entry thresholds + narrative must be EMERGING or PEAKING -> possible_entry
    6. Check high_potential_watch -> high_potential_watch
    7. Check take_profit_watch (only if prior alert was high tier and narrative PEAKING/DECLINING) -> take_profit_watch
    8. Check verify (net_potential >= threshold but confidence < verify_max) -> verify
    9. Check watch -> watch
    10. Otherwise -> ignore

    Conservative tie-breaking: when a value falls exactly on a boundary threshold,
    classify downward (more conservative type). This means >= on minimums uses strict >
    for upgrade thresholds except where the docs specify >= explicitly. For max thresholds
    (e.g. pe_max_p_failure) the boundary value is treated as failing the check.
    """
    if thresholds is None:
        thresholds = AlertThresholds()

    # ------------------------------------------------------------------
    # 1. Discard flags — immediate discard
    # ------------------------------------------------------------------
    for flag in risk_flags:
        if flag in thresholds.discard_flags:
            return "discard"

    # ------------------------------------------------------------------
    # 2. Discard thresholds — p_failure extremely high OR net_potential negligible
    #    Docs: P_failure >= 0.80 OR net_potential < 0.10
    #    Conservative: boundary p_failure==0.80 -> discard; boundary net==0.10 -> NOT discard
    # ------------------------------------------------------------------
    if p_failure >= thresholds.discard_min_p_failure:
        return "discard"
    if net_potential < thresholds.discard_max_net_potential:
        return "discard"

    # ------------------------------------------------------------------
    # 3. Exit risk — only if a prior alert exists and p_failure is high
    #    Docs: P_failure >= 0.65, prior alert exists
    #    Conservative: boundary p_failure==0.65 -> exit_risk (conservative = warn)
    # ------------------------------------------------------------------
    if has_prior_alert and p_failure >= thresholds.exit_risk_min_p_failure:
        return "exit_risk"

    # ------------------------------------------------------------------
    # 4. Blocking flags — if any blocking flag is present, cap at verify
    #    We still evaluate below but will not return anything above verify.
    # ------------------------------------------------------------------
    has_blocking_flag = any(flag in thresholds.blocking_flags for flag in risk_flags)

    # ------------------------------------------------------------------
    # 5. Possible entry — strict criteria
    #    Docs: net_potential >= 0.60, P_failure < 0.30, confidence >= 0.65,
    #          narrative EMERGING or PEAKING, no critical risk flags
    #    Conservative tie-breaking:
    #      net_potential on boundary 0.60 -> meets (docs say >=)
    #      p_failure on boundary 0.30 -> does NOT meet (docs say <, boundary fails)
    #      confidence on boundary 0.65 -> meets (docs say >=)
    # ------------------------------------------------------------------
    if not has_blocking_flag:
        if (
            net_potential >= thresholds.pe_min_net_potential
            and p_failure < thresholds.pe_max_p_failure
            and confidence >= thresholds.pe_min_confidence
            and narrative_state in _ACTIVE_NARRATIVE_STATES
        ):
            return "possible_entry"

    # ------------------------------------------------------------------
    # 6. High potential watch
    #    Docs: net_potential >= 0.45, P_failure < 0.50, confidence >= 0.55,
    #          narrative EMERGING or PEAKING
    #    Conservative:
    #      net_potential on boundary 0.45 -> meets (>=)
    #      p_failure on boundary 0.50 -> does NOT meet (<, boundary fails)
    #      confidence on boundary 0.55 -> meets (>=)
    # ------------------------------------------------------------------
    if not has_blocking_flag:
        if (
            net_potential >= thresholds.hpw_min_net_potential
            and p_failure < thresholds.hpw_max_p_failure
            and confidence >= thresholds.hpw_min_confidence
            and narrative_state in _ACTIVE_NARRATIVE_STATES
        ):
            return "high_potential_watch"

    # ------------------------------------------------------------------
    # 7. Take profit watch — only for tokens with prior high-tier alerts
    #    Docs: prior alert was possible_entry or high_potential_watch,
    #          net_potential still >= 0.35, narrative PEAKING or early DECLINING
    # ------------------------------------------------------------------
    if (
        has_prior_alert
        and prior_alert_type in _HIGH_TIER_TYPES
        and net_potential >= thresholds.verify_min_net_potential
        and narrative_state in _TAKE_PROFIT_NARRATIVE_STATES
    ):
        return "take_profit_watch"

    # ------------------------------------------------------------------
    # 8. Verify — meaningful signal but low confidence
    #    Docs: net_potential >= 0.35, confidence < 0.55
    #    Conservative: confidence on boundary 0.55 -> does NOT meet (<, not verify)
    # ------------------------------------------------------------------
    if (
        net_potential >= thresholds.verify_min_net_potential
        and confidence < thresholds.verify_max_confidence
    ):
        return "verify"

    # ------------------------------------------------------------------
    # 9. Watch — low-level signal
    #    Docs: net_potential >= 0.25
    # ------------------------------------------------------------------
    if net_potential >= thresholds.watch_min_net_potential:
        return "watch"

    # ------------------------------------------------------------------
    # 10. Ignore — below all thresholds
    # ------------------------------------------------------------------
    return "ignore"
