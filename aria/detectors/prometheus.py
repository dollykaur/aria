import requests
import logging
from datetime import datetime
from aria.models import Anomaly, Severity

logger = logging.getLogger(__name__)


class PrometheusDetector:
    def __init__(self, config):
        self.config = config

    def check(self) -> list[Anomaly]:
        anomalies = []
        for rule in self.config.anomaly_rules:
            try:
                results = self._instant_query(rule["query"])
                for item in results:
                    anomalies.append(Anomaly(
                        rule_name=rule["name"],
                        query=rule["query"],
                        value=float(item["value"][1]),
                        severity=Severity(rule.get("severity", "warning")),
                        detected_at=datetime.utcnow(),
                        labels=item.get("metric", {}),
                    ))
            except Exception as e:
                logger.warning("Rule '%s' check failed: %s", rule["name"], e)
        return anomalies

    def _instant_query(self, query: str) -> list:
        resp = requests.get(
            f"{self.config.url}/api/v1/query",
            params={"query": query},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()["data"]["result"]
