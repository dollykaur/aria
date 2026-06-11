import time
import logging
import anthropic

from aria.models import Anomaly, Diagnosis, ActionTaken
from aria.agent.tools import TOOL_DEFINITIONS
from aria.agent.system_prompt import build_system_prompt
from aria.tools.base import ToolRegistry

logger = logging.getLogger(__name__)


def investigate(anomalies: list[Anomaly], config) -> Diagnosis:
    client = anthropic.Anthropic(api_key=config.anthropic_api_key)
    registry = ToolRegistry(config)
    start = time.monotonic()

    anomaly_text = "\n".join(
        f"- [{a.severity.upper()}] {a.rule_name}: value={a.value:.4f}, labels={a.labels}"
        for a in anomalies
    )
    initial_message = (
        f"The following anomalies were detected at {anomalies[0].detected_at.isoformat()}:\n\n"
        f"{anomaly_text}\n\n"
        "Please investigate, identify the root cause, and take one safe remediation action if appropriate."
    )

    messages = [{"role": "user", "content": initial_message}]
    action_taken = ActionTaken(action_type="none", success=True, detail="None — monitoring recommended")
    final_text = ""

    for iteration in range(config.max_tool_iterations):
        logger.info("Agent iteration %d/%d", iteration + 1, config.max_tool_iterations)

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

            logger.info("Tool call: %s(%s)", block.name, block.input)
            result = registry.execute(block.name, block.input)
            logger.info("Tool result (success=%s): %s", result.success, result.content[:200])

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
    return _parse_diagnosis(anomalies, final_text, action_taken, duration)


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
