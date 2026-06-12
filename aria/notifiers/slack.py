import requests
import logging
from aria.models import Diagnosis, Severity
from aria.notifiers.base import BaseNotifier

logger = logging.getLogger(__name__)


class SlackNotifier(BaseNotifier):
    def __init__(self, config):
        self.webhook_url = config.webhook_url

    def post(self, diagnosis: Diagnosis):
        if not self.webhook_url:
            logger.warning("Slack webhook not configured — printing diagnosis to console")
            self._print_to_console(diagnosis)
            return

        is_critical = any(a.severity == Severity.CRITICAL for a in diagnosis.anomalies)
        emoji = ":rotating_light:" if is_critical else ":warning:"

        anomaly_list = "\n".join(
            f"• [{a.severity.upper()}] {a.rule_name} (value={a.value:.4f})"
            for a in diagnosis.anomalies
        )
        recommendations = "\n".join(f"• {r}" for r in diagnosis.recommendations) or "• Continue monitoring"

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"{emoji} ARIA Incident Report"}
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Anomalies Detected:*\n{anomaly_list}"}
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Root Cause:*\n{diagnosis.root_cause}"}
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Recommendations:*\n{recommendations}"}
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Action Taken:* `{diagnosis.action_taken.action_type}` — {diagnosis.action_taken.detail}"
                }
            },
            {
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": f"Investigation completed in {diagnosis.investigation_duration_seconds}s"
                }]
            }
        ]

        try:
            resp = requests.post(self.webhook_url, json={"blocks": blocks}, timeout=10)
            resp.raise_for_status()
            logger.info("Slack notification posted successfully")
        except requests.RequestException as e:
            logger.error("Failed to post to Slack: %s", e)
            self._print_to_console(diagnosis)

    def _print_to_console(self, diagnosis: Diagnosis):
        print("\n" + "="*60)
        print("ARIA DIAGNOSIS")
        print("="*60)
        for a in diagnosis.anomalies:
            print(f"[{a.severity.upper()}] {a.rule_name}: {a.value:.4f}")
        print(f"\nROOT CAUSE: {diagnosis.root_cause}")
        print(f"\nACTION TAKEN: {diagnosis.action_taken.detail}")
        for r in diagnosis.recommendations:
            print(f"  - {r}")
        print(f"\nDuration: {diagnosis.investigation_duration_seconds}s")
        print("="*60 + "\n")
