"""
Pure logic for incident family management — no database calls here.
All DB operations live in store.py; this module only computes.
"""
import re
import json

_RISK_LADDER = ["warning", "elevated", "high", "critical"]

_PROMQL_KEYWORDS = {
    "rate", "increase", "irate", "delta", "sum", "avg", "max", "min",
    "count", "by", "without", "on", "group_left", "group_right",
    "histogram_quantile", "label_replace", "offset", "bool", "or",
    "and", "unless", "ignoring", "with",
}

_SEVERITY_PREFIXES = ("High ", "Low ", "Elevated ", "Critical ", "Slow ", "Fast ")


def generate_name(anomalies: list) -> str:
    """
    Strip leading severity words to produce a stable family name.
    'High CPU Usage' → 'CPU Usage'   (recurs as the same family across severity changes)
    """
    name = anomalies[0].rule_name
    for prefix in _SEVERITY_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def extract_metric_names(anomalies: list) -> set[str]:
    """Pull raw Prometheus metric identifiers from PromQL query strings."""
    metrics: set[str] = set()
    for a in anomalies:
        tokens = set(re.findall(r'\b[a-z_][a-z0-9_]*\b', a.query.lower()))
        metrics |= tokens - _PROMQL_KEYWORDS
    return metrics


def fingerprint_score(incoming_anomalies: list, family: dict) -> float:
    """
    How well do incoming anomalies match a stored family fingerprint?

    60% metric signal overlap — what Prometheus metrics actually fired
    40% rule-name token overlap — what the alerts are called

    Metric signals are weighted higher because alert names can be renamed
    while the underlying metric (system_cpu_usage) stays stable.
    """
    in_tokens: set[str] = set()
    for a in incoming_anomalies:
        in_tokens |= set(a.rule_name.lower().split())

    fam_tokens: set[str] = set()
    for name in json.loads(family.get("anomaly_names", "[]")):
        fam_tokens |= set(name.lower().split())

    in_metrics = extract_metric_names(incoming_anomalies)
    fam_metrics = set(json.loads(family.get("metric_names", "[]")))

    def jaccard(a: set, b: set) -> float:
        u = a | b
        return len(a & b) / len(u) if u else 0.0

    return 0.40 * jaccard(in_tokens, fam_tokens) + 0.60 * jaccard(in_metrics, fam_metrics)


def compute_trend(snapshots: list[dict]) -> tuple[str, float]:
    """
    Compare first vs last metric value snapshot.
    Returns (trend_label, pct_change).

    'worsening'  — values increased >15% from first occurrence
    'recovering' — values decreased >15%
    'stable'     — within ±15%
    """
    if len(snapshots) < 2:
        return "stable", 0.0
    first = snapshots[0]["value"]
    last = snapshots[-1]["value"]
    if first == 0:
        return "stable", 0.0
    pct = ((last - first) / first) * 100
    if pct > 15:
        return "worsening", round(pct, 1)
    if pct < -15:
        return "recovering", round(pct, 1)
    return "stable", round(pct, 1)


def compute_risk(severity: str, occurrence_count: int, trend: str) -> str:
    """
    Escalate risk beyond the base alert severity.

    Escalation triggers (each adds one step on the ladder):
      - Trend is worsening
      - 4+ occurrences of the same family

    Ladder: warning → elevated → high → critical
    """
    risk = severity if severity in _RISK_LADDER else "warning"
    if trend == "worsening":
        risk = _escalate(risk)
    if occurrence_count >= 4:
        risk = _escalate(risk)
    return risk


def _escalate(level: str) -> str:
    idx = _RISK_LADDER.index(level) if level in _RISK_LADDER else 0
    return _RISK_LADDER[min(idx + 1, len(_RISK_LADDER) - 1)]
