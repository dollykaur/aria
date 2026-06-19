import json
import logging
from aria.models import Anomaly
from aria.memory.store import get_recent_incidents

logger = logging.getLogger(__name__)


def find_similar_incidents(anomalies: list[Anomaly], threshold: float = 0.5) -> list[dict]:
    """
    Compare incoming anomalies against past incidents.
    Returns a list of similar past incidents sorted by similarity score.

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

        # Same anomaly types detected
        if incoming_names == past_names:
            score += 0.5
        elif incoming_names & past_names:
            # Partial overlap — some same anomaly types
            overlap = len(incoming_names & past_names) / len(incoming_names | past_names)
            score += 0.5 * overlap

        # Same services affected
        if incoming_services == past_services:
            score += 0.3
        elif incoming_services & past_services:
            overlap = len(incoming_services & past_services) / len(incoming_services | past_services)
            score += 0.3 * overlap

        # Past incident was resolved
        if incident["resolved"]:
            score += 0.2

        if score >= threshold:
            scored.append((score, incident))

    # Sort by score descending — best match first
    scored.sort(key=lambda x: x[0], reverse=True)
    return [incident for _, incident in scored[:3]]  # return top 3 matches


def build_memory_context(similar_incidents: list[dict]) -> str:
    """
    Format past incidents into plain English for Claude to read.
    This gets injected into Claude's investigation context.
    """
    if not similar_incidents:
        return ""

    lines = [
        "PAST SIMILAR INCIDENTS (use this context to guide your investigation):\n"
    ]

    for i, incident in enumerate(similar_incidents, 1):
        detected = incident["detected_at"][:16].replace("T", " ")
        anomaly_names = json.loads(incident["anomaly_names"])
        services = json.loads(incident["affected_services"])
        action = incident["action_taken"]
        resolved = "Yes" if incident["resolved"] else "No"
        duration = incident["investigation_duration_seconds"]

        lines.append(f"Incident #{i} — {detected}")
        lines.append(f"  Anomalies : {', '.join(anomaly_names)}")
        lines.append(f"  Services  : {', '.join(services)}")
        lines.append(f"  Root cause: {incident['root_cause']}")
        lines.append(f"  Action    : {action}")
        lines.append(f"  Resolved  : {resolved} (investigated in {duration}s)")

        if incident["container_restarted"]:
            lines.append(f"  Restarted : {incident['container_restarted']}")

        recommendations = json.loads(incident.get("evidence", "[]"))
        if recommendations:
            lines.append(f"  Key findings:")
            for r in recommendations[:2]:
                lines.append(f"    - {r}")

        lines.append("")

    lines.append(
        "If the current anomaly matches a past incident pattern, "
        "confirm the hypothesis quickly and apply the known fix if still appropriate.\n"
    )

    return "\n".join(lines)
