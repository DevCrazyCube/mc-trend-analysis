"""Format alerts for delivery to output channels."""

from datetime import datetime, timezone


# Alert type display config
ALERT_TYPE_ICONS = {
    "possible_entry": "\u2705",      # green check
    "high_potential_watch": "\U0001f7e1",  # yellow circle
    "take_profit_watch": "\U0001f7e0",     # orange circle
    "verify": "\U0001f535",           # blue circle
    "watch": "\u26aa",               # white circle
    "exit_risk": "\U0001f534",        # red circle
    "discard": "\u274c",             # X
}

ALERT_TYPE_LABELS = {
    "possible_entry": "POSSIBLE ENTRY",
    "high_potential_watch": "HIGH-POTENTIAL WATCH",
    "take_profit_watch": "TAKE-PROFIT WATCH",
    "verify": "VERIFY",
    "watch": "WATCH",
    "exit_risk": "EXIT-RISK",
    "discard": "DISCARD",
}


def format_alert_text(alert: dict) -> str:
    """Format an alert as plain text for console/log output."""
    alert_type = alert.get("alert_type", "unknown")
    label = ALERT_TYPE_LABELS.get(alert_type, alert_type.upper())
    icon = ALERT_TYPE_ICONS.get(alert_type, "")

    token_name = alert.get("token_name", "UNKNOWN")
    token_symbol = alert.get("token_symbol", "")
    token_address = alert.get("token_address", "")
    narrative_name = alert.get("narrative_name", "Unknown narrative")
    net_potential = alert.get("net_potential", 0)
    p_potential = alert.get("p_potential", 0)
    p_failure = alert.get("p_failure", 0)
    confidence = alert.get("confidence_score", 0)
    risk_flags = alert.get("risk_flags", [])
    reasoning = alert.get("reasoning", "")
    expires_at = alert.get("expires_at", "")

    dims = alert.get("dimension_scores", {})
    if isinstance(dims, dict):
        dim_lines = []
        for key in ["narrative_relevance", "og_score", "rug_risk", "momentum_quality",
                     "attention_strength", "timing_quality"]:
            val = dims.get(key)
            if val is not None:
                dim_lines.append(f"  {key}: {val:.2f}")
    else:
        dim_lines = []

    flags_str = ", ".join(risk_flags) if risk_flags else "none detected"

    lines = [
        f"{icon} {label} — ${token_symbol} ({token_name})",
        "=" * 50,
        f"Narrative: {narrative_name}",
        f"net_potential: {net_potential:.2f} | confidence: {confidence:.2f}",
        f"P_potential: {p_potential:.2f} | P_failure: {p_failure:.2f}",
        "",
        "Risk Flags: " + flags_str,
        "",
    ]

    if dim_lines:
        lines.append("Dimension Scores:")
        lines.extend(dim_lines)
        lines.append("")

    if reasoning:
        lines.append("Reasoning:")
        lines.append(reasoning)
        lines.append("")

    lines.append(f"Address: {token_address}")
    lines.append(f"Expires: {expires_at}")
    lines.append(f"Alert ID: {alert.get('alert_id', 'N/A')}")

    return "\n".join(lines)


def format_alert_telegram(alert: dict) -> str:
    """Format an alert for Telegram delivery (markdown-compatible)."""
    alert_type = alert.get("alert_type", "unknown")
    label = ALERT_TYPE_LABELS.get(alert_type, alert_type.upper())
    icon = ALERT_TYPE_ICONS.get(alert_type, "")

    token_symbol = alert.get("token_symbol", "")
    narrative_name = alert.get("narrative_name", "")
    net_potential = alert.get("net_potential", 0)
    p_potential = alert.get("p_potential", 0)
    p_failure = alert.get("p_failure", 0)
    confidence = alert.get("confidence_score", 0)
    risk_flags = alert.get("risk_flags", [])
    reasoning = alert.get("reasoning", "")
    token_address = alert.get("token_address", "")
    expires_at = alert.get("expires_at", "")

    flags_str = ", ".join(risk_flags) if risk_flags else "none"

    # Use basic formatting compatible with Telegram's parse_mode
    lines = [
        f"{icon} *{label}* — ${token_symbol}",
        f"Narrative: {narrative_name}",
        f"net\\_potential: {net_potential:.2f} | confidence: {confidence:.2f}",
        f"P\\_potential: {p_potential:.2f} | P\\_failure: {p_failure:.2f}",
        "",
        f"⚠️ Risk Flags: {flags_str}",
        "",
    ]

    if reasoning:
        # Truncate for Telegram (max ~4096 chars total)
        truncated = reasoning[:800] + ("..." if len(reasoning) > 800 else "")
        lines.append(truncated)
        lines.append("")

    lines.append(f"Address: `{token_address}`")
    lines.append(f"Expires: {expires_at}")

    return "\n".join(lines)


def format_alert_json(alert: dict) -> dict:
    """Format an alert as a clean JSON-serializable dict for webhook delivery."""
    return {
        "alert_id": alert.get("alert_id"),
        "alert_type": alert.get("alert_type"),
        "token": {
            "name": alert.get("token_name"),
            "symbol": alert.get("token_symbol"),
            "address": alert.get("token_address"),
        },
        "narrative": {
            "id": alert.get("narrative_id"),
            "name": alert.get("narrative_name"),
        },
        "scores": {
            "net_potential": alert.get("net_potential"),
            "p_potential": alert.get("p_potential"),
            "p_failure": alert.get("p_failure"),
            "confidence": alert.get("confidence_score"),
        },
        "dimension_scores": alert.get("dimension_scores"),
        "risk_flags": alert.get("risk_flags", []),
        "reasoning": alert.get("reasoning"),
        "status": alert.get("status"),
        "created_at": alert.get("created_at"),
        "expires_at": alert.get("expires_at"),
    }


def format_digest(alerts: list[dict]) -> str:
    """Format multiple alerts as a digest summary."""
    if not alerts:
        return "DIGEST — No signals in this period."

    now_str = datetime.now(timezone.utc).strftime("%H:%M UTC")
    lines = [f"DIGEST — {len(alerts)} signals as of {now_str}", ""]

    for i, alert in enumerate(alerts, 1):
        alert_type = alert.get("alert_type", "unknown")
        label = ALERT_TYPE_LABELS.get(alert_type, alert_type.upper())
        icon = ALERT_TYPE_ICONS.get(alert_type, "")
        token_symbol = alert.get("token_symbol", "?")
        narrative_name = alert.get("narrative_name", "?")
        net = alert.get("net_potential", 0)
        conf = alert.get("confidence_score", 0)
        flags = alert.get("risk_flags", [])

        flag_str = ""
        if flags:
            flag_str = " | " + ", ".join(flags[:2])
            if len(flags) > 2:
                flag_str += f" +{len(flags) - 2} more"

        lines.append(
            f"{i}. {icon} {label} — ${token_symbol} | {narrative_name} | "
            f"net: {net:.2f} | conf: {conf:.2f}{flag_str}"
        )

    return "\n".join(lines)
