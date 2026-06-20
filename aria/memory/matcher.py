import re
import json
import logging
from datetime import datetime
from aria.models import Anomaly
from aria.memory.store import get_recent_incidents

logger = logging.getLogger(__name__)

# Above this score Claude gets a structured "known pattern" block and can skip
# deep investigation. Below it Claude gets hints but must still investigate.
HIGH_SIMILARITY_THRESHOLD = 0.85

# ── Scoring weights — must sum to 1.0 ────────────────────────────────────────
_W_ANOMALY_TYPE = 0.40   # what kind of alert fired
_W_SERVICES     = 0.25   # which services were affected
_W_METRICS      = 0.20   # which raw Prometheus metrics appeared in the queries
_W_TIME_OF_DAY  = 0.15   # same hour-of-day (catches scheduled-job patterns)

_PROMQL_KEYWORDS = {
    "rate", "increase", "irate", "delta", "sum", "avg", "max", "min",
    "count", "by", "without", "on", "group_left", "group_right",
    "histogram_quantile", "label_replace", "offset", "bool", "or",
    "and", "unless", "ignoring", "with",
}


def _jaccard(a: set, b: set) -> float:
    """Intersection over union. Returns 0 when both sets are empty."""
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def _name_tokens(rule_name: str) -> set[str]:
    """Split 'High CPU Usage' → {'high', 'cpu', 'usage'} for soft matching."""
    return set(rule_name.lower().split())


def _extract_metrics(query: str) -> set[str]:
    """Pull raw metric identifiers out of a PromQL expression."""
    tokens = set(re.findall(r'\b[a-z_][a-z0-9_]*\b', query.lower()))
    return tokens - _PROMQL_KEYWORDS


def _temporal_score(past_iso: str, current_dt: datetime) -> float:
    """
    Score based on hour-of-day proximity (UTC).
    Same hour → 1.0 | ±1 h → 0.5 | ±2 h → 0.25 | further → 0.0
    """
    try:
        past_hour = datetime.fromisoformat(past_iso).hour
    except ValueError:
        return 0.0
    diff = abs(current_dt.hour - past_hour)
    diff = min(diff, 24 - diff)  # wrap around midnight
    if diff == 0:
        return 1.0
    if diff == 1:
        return 0.5
    if diff == 2:
        return 0.25
    return 0.0


def find_similar_incidents(
    anomalies: list[Anomaly], threshold: float = 0.4
) -> list[tuple[float, dict]]:
    """
    Score past incidents against the incoming anomaly set across four
    independent dimensions:

      40% — anomaly type  (word-token Jaccard on rule names)
      25% — affected services (set Jaccard)
      20% — metric signals  (Jaccard on raw PromQL metric identifiers)
      15% — time-of-day     (hour proximity, catches scheduled-job patterns)

    Each dimension is a proper Jaccard ratio in [0, 1], so no single dimension
    can manufacture a misleadingly high total score.
    """
    past_incidents = get_recent_incidents(limit=20)
    if not past_incidents:
        return []

    # Pre-compute incoming fingerprint once
    incoming_name_tokens: set[str] = set()
    for a in anomalies:
        incoming_name_tokens |= _name_tokens(a.rule_name)

    incoming_services = {
        a.labels.get("application", a.labels.get("job", "unknown"))
        for a in anomalies
    }

    incoming_metrics: set[str] = set()
    for a in anomalies:
        incoming_metrics |= _extract_metrics(a.query)

    current_dt = anomalies[0].detected_at

    scored = []
    for incident in past_incidents:
        past_name_tokens: set[str] = set()
        for name in json.loads(incident["anomaly_names"]):
            past_name_tokens |= _name_tokens(name)

        past_services  = set(json.loads(incident["affected_services"]))
        past_metrics   = set(json.loads(incident.get("metric_names") or "[]"))

        dim_type    = _jaccard(incoming_name_tokens, past_name_tokens)
        dim_service = _jaccard(incoming_services, past_services)
        dim_metric  = _jaccard(incoming_metrics, past_metrics) if past_metrics else 0.0
        dim_time    = _temporal_score(incident["detected_at"], current_dt)

        score = (
            _W_ANOMALY_TYPE * dim_type
            + _W_SERVICES   * dim_service
            + _W_METRICS    * dim_metric
            + _W_TIME_OF_DAY * dim_time
        )

        if score >= threshold:
            scored.append((score, incident))

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:3]


def build_memory_context(similar: list[tuple[float, dict]]) -> str:
    """
    Build the memory block injected into Claude's investigation prompt.

    High similarity (≥ 85%): structured "known pattern" block — Claude confirms
    quickly rather than re-investigating from scratch.

    Low-medium similarity (< 85%): free-text hints — Claude uses them as
    hypotheses but still does a full investigation.
    """
    if not similar:
        return ""

    top_score, top_incident = similar[0]

    if top_score >= HIGH_SIMILARITY_THRESHOLD:
        return _build_known_pattern_block(top_score, top_incident, len(similar))
    else:
        return _build_hint_block(similar)


def _build_known_pattern_block(score: float, incident: dict, match_count: int) -> str:
    """
    Structured context for high-confidence matches.
    Tells Claude exactly what happened before so it can confirm fast.
    """
    pct = int(score * 100)
    detected = incident["detected_at"][:16].replace("T", " ")
    services = json.loads(incident["affected_services"])
    recommendations = json.loads(incident.get("evidence", "[]"))
    action = incident["action_taken"]
    duration = incident["investigation_duration_seconds"]

    recs_text = (
        "\n".join(f"  - {r}" for r in recommendations[:3])
        if recommendations
        else "  - No specific recommendations recorded"
    )

    lines = [
        f"KNOWN INCIDENT PATTERN DETECTED (similarity: {pct}%)",
        "",
        f"This appears to be a recurrence of a known incident pattern seen {match_count} time(s).",
        "Review the known facts below, verify they still apply, then respond with your diagnosis.",
        "",
        f"KNOWN ROOT CAUSE  : {incident['root_cause']}",
        f"KNOWN ACTION TAKEN: {action}",
        f"KNOWN OUTCOME     : {'Resolved' if incident['resolved'] else 'Unresolved'} (investigated in {duration}s)",
        f"AFFECTED SERVICES : {', '.join(services)}",
        f"LAST SEEN         : {detected}",
        f"OCCURRENCES       : {match_count}",
        "",
        "KNOWN RECOMMENDATIONS:",
        recs_text,
        "",
        "INSTRUCTIONS:",
        "- Use query_prometheus to quickly confirm the known root cause still applies.",
        "- If confirmed: state the root cause, note this is a known recurrence, and apply the known fix if still appropriate.",
        "- If NOT confirmed: investigate normally and note what differs from the known pattern.",
        "",
    ]
    return "\n".join(lines)


def _build_hint_block(similar: list[tuple[float, dict]]) -> str:
    """
    Free-text hints for low-medium similarity matches.
    Claude uses these as starting hypotheses, not confirmed facts.
    """
    lines = ["PAST SIMILAR INCIDENTS (treat as hints — investigate fully):\n"]

    for i, (score, incident) in enumerate(similar, 1):
        pct = int(score * 100)
        detected = incident["detected_at"][:16].replace("T", " ")
        anomaly_names = json.loads(incident["anomaly_names"])
        services = json.loads(incident["affected_services"])
        recommendations = json.loads(incident.get("evidence", "[]"))

        lines.append(f"Incident #{i} — {detected} (similarity: {pct}%)")
        lines.append(f"  Anomalies : {', '.join(anomaly_names)}")
        lines.append(f"  Services  : {', '.join(services)}")
        lines.append(f"  Root cause: {incident['root_cause']}")
        lines.append(f"  Action    : {incident['action_taken']}")
        lines.append(f"  Resolved  : {'Yes' if incident['resolved'] else 'No'}")

        if incident["container_restarted"]:
            lines.append(f"  Restarted : {incident['container_restarted']}")

        if recommendations:
            lines.append("  Key findings:")
            for r in recommendations[:2]:
                lines.append(f"    - {r}")

        lines.append("")

    lines.append(
        "These are partial matches. Investigate fully and use past incidents "
        "only as starting hypotheses.\n"
    )
    return "\n".join(lines)
