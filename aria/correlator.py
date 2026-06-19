from aria.models import Anomaly, CorrelatedIncident, Severity

# Prometheus label keys that identify a service — checked in priority order
_SERVICE_LABEL_KEYS = ("application", "job", "service", "instance")


def _severity_rank(s: Severity) -> int:
    return 1 if s == Severity.CRITICAL else 0


def _extract_service(labels: dict[str, str]) -> str | None:
    for key in _SERVICE_LABEL_KEYS:
        if key in labels:
            return labels[key]
    return None


def correlate(anomalies: list[Anomaly]) -> list[CorrelatedIncident]:
    """
    Group anomalies that share the same rule name into one CorrelatedIncident.

    Four "High CPU Usage" anomalies from four services → one incident titled
    "Fleet-wide High CPU Usage" with all four services listed. Claude then
    investigates once instead of four times.
    """
    groups: dict[str, list[Anomaly]] = {}
    for anomaly in anomalies:
        groups.setdefault(anomaly.rule_name, []).append(anomaly)

    incidents: list[CorrelatedIncident] = []
    for rule_name, group in groups.items():
        # Deduplicate service names while preserving order
        seen: set[str] = set()
        services: list[str] = []
        for a in group:
            svc = _extract_service(a.labels)
            if svc and svc not in seen:
                seen.add(svc)
                services.append(svc)

        # Escalate to the highest severity in the group
        severity = max(group, key=lambda a: _severity_rank(a.severity)).severity

        # "Fleet-wide" prefix only when multiple services are involved
        title = f"Fleet-wide {rule_name}" if len(group) > 1 else rule_name

        incidents.append(CorrelatedIncident(
            title=title,
            severity=severity,
            anomalies=group,
            affected_services=services,
        ))

    # Investigate critical incidents before warnings
    incidents.sort(key=lambda i: _severity_rank(i.severity), reverse=True)
    return incidents
