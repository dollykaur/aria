"""
Adaptive investigation router.

Classifies the incoming anomaly set by signal type, then produces a
structured SUGGESTED INVESTIGATION PATH that gets injected into Claude's
initial message. Claude follows this path instead of checking every tool
blindly on every investigation.

Adding a new anomaly class: add a key to _classify(), add a branch in
_build_path(), done. No changes to Claude's tool definitions needed.
"""
from aria.models import Anomaly


# ── Signal classification ──────────────────────────────────────────────────

def _classify(anomalies: list[Anomaly]) -> dict[str, bool]:
    """
    Scan rule names and raw PromQL queries to detect which signal classes
    are present. One investigation can belong to multiple classes.
    """
    combined = " ".join(
        f"{a.rule_name} {a.query}".lower()
        for a in anomalies
    )

    return {
        "jvm_gc":      any(t in combined for t in ("jvm_gc", "gc_pause", "garbage")),
        "jvm_heap":    any(t in combined for t in ("jvm_memory", "heap")),
        "host_cpu":    any(t in combined for t in ("system_cpu_usage", "process_cpu")),
        "kafka":       any(t in combined for t in ("kafka", "consumer_lag", "listener")),
        "db_pool":     any(t in combined for t in ("hikaricp", "connection_pool", "hikari")),
        "slow_query":  any(t in combined for t in ("slow", "pg_stat", "query_time")),
        "http_errors": any(t in combined for t in ("http_server", "5xx", "status=~\"5", "failed_total", "dlq")),
        "dlq":         "dlq" in combined,
    }


# ── Path builder ───────────────────────────────────────────────────────────

class _Path:
    def __init__(self):
        self.steps: list[str] = []
        self.skip: list[str] = []

    def focus(self, *steps: str) -> "_Path":
        self.steps.extend(steps)
        return self

    def defer(self, *tools: str) -> "_Path":
        self.skip.extend(tools)
        return self


def _build_path(signals: dict[str, bool]) -> _Path:
    p = _Path()

    if signals["jvm_gc"]:
        p.focus(
            "JVM GC pause rates and cumulative pause time per service",
            "JVM heap usage (heap pressure drives GC burst)",
            "Kafka consumer lag (GC pauses cause consumer slowness as a side effect)",
        ).defer("PostgreSQL slow queries", "host-level CPU deep dive")

    elif signals["jvm_heap"]:
        p.focus(
            "JVM heap used vs max across all services",
            "JVM GC pause frequency (heap pressure → GC escalation)",
            "HTTP error rates (heap exhaustion causes 5xx)",
        ).defer("PostgreSQL", "Kafka (check only if delivery failures present)")

    elif signals["host_cpu"]:
        p.focus(
            "process_cpu_usage vs system_cpu_usage (distinguish app vs OS load)",
            "JVM GC pause rates (CPU spikes are often GC-driven on JVM services)",
            "HTTP request rates and active thread counts",
        ).defer(
            "PostgreSQL (check only if connection pool or slow query alerts present)",
            "Kafka (check only if consumer lag alerts present)",
        )

    elif signals["kafka"] or signals["dlq"]:
        p.focus(
            "Kafka consumer lag per consumer group",
            "Notification delivery failure and DLQ rates",
            "JVM GC on consumer services (GC pauses stall consumers)",
        ).defer("PostgreSQL", "host CPU (check only if system_cpu alert is also firing)")

    elif signals["db_pool"] or signals["slow_query"]:
        p.focus(
            "PostgreSQL slow queries (threshold: current config)",
            "HikariCP pending connections and pool saturation",
            "HTTP error rates from services that depend on the DB",
        ).defer("Kafka", "JVM GC (check only if heap alert is also present)")

    elif signals["http_errors"]:
        p.focus(
            "HTTP 5xx error rates by service and endpoint",
            "PostgreSQL slow queries (DB latency often causes upstream 5xx)",
            "Kafka consumer lag (message processing failures surface as 5xx)",
        )

    else:
        # Unknown signal class — full investigation, no skip
        p.focus(
            "Prometheus metrics for the specific rule that fired",
            "Correlate across services before expanding to other tools",
        )

    return p


# ── Public API ─────────────────────────────────────────────────────────────

def suggest_investigation_path(anomalies: list[Anomaly]) -> str:
    """
    Return a formatted investigation path block to inject into Claude's
    initial message. Empty string if the anomaly set is unclassifiable.
    """
    signals = _classify(anomalies)
    path = _build_path(signals)

    if not path.steps:
        return ""

    lines = ["SUGGESTED INVESTIGATION PATH:"]
    for i, step in enumerate(path.steps, 1):
        lines.append(f"  {i}. {step}")

    if path.skip:
        lines.append(
            f"DEFER UNTIL EVIDENCE WARRANTS: {', '.join(path.skip)}"
        )

    lines.append("")
    return "\n".join(lines) + "\n"
