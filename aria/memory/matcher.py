import json
import logging
from aria.models import Anomaly
from aria.memory.store import get_recent_incidents

logger = logging.getLogger(__name__)

# Above this score Claude gets a structured "known pattern" block and can skip
# deep investigation. Below it Claude gets hints but must still investigate.
HIGH_SIMILARITY_THRESHOLD = 0.85


def find_similar_incidents(
    anomalies: list[Anomaly], threshold: float = 0.5
) -> list[tuple[float, dict]]:
    """
    Compare incoming anomalies against past incidents.
    Returns (score, incident) tuples sorted by score descending.

    Scoring:
      +0.5 — same anomaly rule names
      +0.3 — same affected services
      +0.2 — incident was resolved successfully
    """
    past_incidents = get_recent_incidents(limit=20)
    if not past_incidents:
        return []

    incoming_names = set(a.rule_name for a in anomalies)
    incoming_services = set(
        a.labels.get("application", a.labels.get("job", "unknown"))
        for a in anomalies
    )

    scored = []
    for incident in past_incidents:
        score = 0.0
        past_names = set(json.loads(incident["anomaly_names"]))
        past_services = set(json.loads(incident["affected_services"]))

        if incoming_names == past_names:
            score += 0.5
        elif incoming_names & past_names:
            overlap = len(incoming_names & past_names) / len(incoming_names | past_names)
            score += 0.5 * overlap

        if incoming_services == past_services:
            score += 0.3
        elif incoming_services & past_services:
            overlap = len(incoming_services & past_services) / len(incoming_services | past_services)
            score += 0.3 * overlap

        if incident["resolved"]:
            score += 0.2

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
