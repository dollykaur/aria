import time
import logging
import anthropic

from aria.models import Anomaly, CorrelatedIncident, Diagnosis, ActionTaken
from aria.agent.tools import TOOL_DEFINITIONS
from aria.agent.system_prompt import build_system_prompt
from aria.tools.base import ToolRegistry
from aria.memory.matcher import find_similar_incidents, build_memory_context
from aria.memory.store import save_incident, find_matching_family, get_accuracy_stats

logger = logging.getLogger(__name__)


def investigate(incident: CorrelatedIncident, config) -> Diagnosis:
    client = anthropic.Anthropic(api_key=config.anthropic_api_key)
    registry = ToolRegistry(config)
    start = time.monotonic()
    anomalies = incident.anomalies

    # Build a structured incident brief for Claude
    services_text = (
        "\n".join(f"  - {s}" for s in incident.affected_services)
        if incident.affected_services
        else "  - (no service label in metrics)"
    )
    signals_text = "\n".join(
        f"  - [{a.severity.upper()}] {a.rule_name}: value={a.value:.4f}, labels={a.labels}"
        for a in anomalies
    )
    incident_brief = (
        f"INCIDENT: {incident.title}\n"
        f"SEVERITY: {incident.severity.upper()}\n"
        f"SIGNAL COUNT: {len(anomalies)}\n"
        f"AFFECTED SERVICES ({len(incident.affected_services)}):\n{services_text}\n\n"
        f"RAW SIGNALS:\n{signals_text}"
    )

    # Check for existing family BEFORE investigation so Claude knows the history.
    # Pass occurrence_count + 1 so Claude's text agrees with the count after save.
    existing_family = find_matching_family(anomalies)
    family_context = _build_family_context(existing_family)

    # Memory context goes to Claude only — do not echo the raw count to console
    # because it would disagree with the family count printed after save.
    similar = find_similar_incidents(anomalies)
    memory_context = build_memory_context(similar)

    # Only surface the confidence label when it's meaningful
    if similar:
        top_score, _ = similar[0]
        if int(top_score * 100) >= 85:
            print(f"  • KNOWN PATTERN ({int(top_score * 100)}% similarity) — Claude will confirm quickly")

    initial_message = (
        f"Incident detected at {anomalies[0].detected_at.isoformat()}:\n\n"
        f"{incident_brief}\n\n"
        f"{family_context}"
        f"{memory_context}"
        "Please investigate, identify the root cause, and take one safe remediation action if appropriate."
    )

    messages = [{"role": "user", "content": initial_message}]
    action_taken = ActionTaken(action_type="none", success=True, detail="None — monitoring recommended")
    final_text = ""

    for iteration in range(config.max_tool_iterations):
        response = client.messages.create(
            model=config.claude_model,
            max_tokens=4096,
            system=build_system_prompt(config),
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            final_text = next((b.text for b in response.content if hasattr(b, "text")), "")
            break

        if response.stop_reason != "tool_use":
            logger.warning("Unexpected stop reason: %s", response.stop_reason)
            break

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue

            print(f"  • {_describe_tool(block.name, block.input)}")
            result = registry.execute(block.name, block.input)
            if not result.success:
                print(f"    ✗ {result.content.splitlines()[0]}")
            else:
                print(f"    ✓ done")

            if block.name == "restart_docker_container" and result.success:
                action_taken = ActionTaken(
                    action_type="restart_container",
                    target=block.input.get("container_name"),
                    success=True,
                    detail=result.content,
                )

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result.content,
                "is_error": not result.success,
            })

        messages.append({"role": "user", "content": tool_results})

    if not final_text:
        final_text = "Investigation reached maximum iterations without a conclusion."

    duration = time.monotonic() - start
    diagnosis = _parse_diagnosis(anomalies, final_text, action_taken, duration)

    # Save to memory — also upserts the incident family
    incident_id, family = save_incident(anomalies, diagnosis)
    _print_family_summary(incident_id, family)

    return diagnosis


def _build_family_context(family: dict | None) -> str:
    """
    Inject incident family history into Claude's prompt.

    We use occurrence_count + 1 so that the number Claude writes in its
    diagnosis ("this is occurrence #4") matches exactly what gets saved
    to the database — one source of truth.
    """
    if not family:
        return ""

    this_occurrence = family["occurrence_count"] + 1
    pct = abs(family.get("metric_pct_change", 0.0))
    trend = family["trend"]
    risk = family["risk_level"].upper()
    first = family["first_seen"][:16].replace("T", " ")
    last = family["last_seen"][:16].replace("T", " ")

    pct_line = ""
    if pct > 5 and trend != "stable":
        direction = "increase" if trend == "worsening" else "decrease"
        pct_line = f"METRIC TREND      : {pct:.1f}% {direction} since first occurrence\n"

    return (
        f"INCIDENT FAMILY   : {family['name']}\n"
        f"FIRST SEEN        : {first}\n"
        f"LAST SEEN         : {last}\n"
        f"OCCURRENCES       : {family['occurrence_count']} previous — this is occurrence #{this_occurrence}\n"
        f"TREND             : {trend.upper()}\n"
        f"{pct_line}"
        f"RISK LEVEL        : {risk}\n\n"
    )


def _print_family_summary(incident_id: str, family: dict):
    n = family["occurrence_count"]  # already incremented by save_incident
    trend = family["trend"].upper()
    risk = family["risk_level"].upper()
    pct = abs(family.get("metric_pct_change", 0.0))
    pct_str = (
        f" | {'+' if family.get('metric_pct_change', 0) > 0 else '-'}{pct:.0f}% metric"
        if pct > 5 else ""
    )

    print(f"\n  Incident Family : {family['name']}")
    print(f"  First Seen      : {family['first_seen'][:16].replace('T', ' ')}")
    print(f"  Last Seen       : {family['last_seen'][:16].replace('T', ' ')}")
    print(f"  Occurrences     : {n}")
    print(f"  Trend           : {trend}{pct_str}")
    print(f"  Risk Level      : {risk}")
    print(f"  Incident ID     : {incident_id}")

    stats = get_accuracy_stats()
    if stats["total"] > 0:
        print(f"\n  Historical Accuracy")
        print(f"  Validated Diagnoses : {stats['total']}")
        print(f"  Correct             : {stats['correct']}")
        print(f"  Incorrect           : {stats['incorrect']}")
        print(f"  Confidence          : {stats['accuracy_pct']}%")


def _describe_tool(name: str, inputs: dict) -> str:
    if name == "query_prometheus":
        return f"Checking metrics — {inputs.get('query', '')[:60]}"
    elif name == "query_pg_slow_queries":
        return f"Checking PostgreSQL for slow queries (last {inputs.get('since_minutes', 15)} mins)"
    elif name == "get_kafka_consumer_lag":
        group = inputs.get("group_id")
        return f"Checking Kafka consumer lag{f' for {group}' if group else ' across all groups'}"
    elif name == "restart_docker_container":
        return f"Restarting container '{inputs.get('container_name')}' — {inputs.get('reason', '')}"
    return name


def _parse_diagnosis(anomalies, text: str, action_taken: ActionTaken, duration: float) -> Diagnosis:
    root_cause = "Unable to determine root cause."
    recommendations = []

    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("ROOT CAUSE:"):
            root_cause = line.replace("ROOT CAUSE:", "").strip()
        elif line.startswith("RECOMMENDATIONS:"):
            for rec_line in lines[i + 1:]:
                if rec_line.startswith("- "):
                    recommendations.append(rec_line[2:].strip())
                elif rec_line.startswith("ACTION TAKEN:"):
                    break

    return Diagnosis(
        anomalies=anomalies,
        root_cause=root_cause,
        recommendations=recommendations,
        action_taken=action_taken,
        investigation_duration_seconds=round(duration, 2),
    )
