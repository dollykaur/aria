import re
import sqlite3
import json
import uuid
import logging
from datetime import datetime
from pathlib import Path
from aria.models import Anomaly, Diagnosis

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "incidents.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create all tables and run any pending column migrations. Called once at startup."""
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS incidents (
                id TEXT PRIMARY KEY,
                detected_at TEXT NOT NULL,
                resolved_at TEXT,
                family_id TEXT,

                anomaly_names TEXT NOT NULL,
                affected_services TEXT NOT NULL,
                metric_names TEXT NOT NULL DEFAULT '[]',

                root_cause TEXT NOT NULL,
                evidence TEXT NOT NULL,
                confidence REAL DEFAULT 0.0,

                action_taken TEXT NOT NULL,
                container_restarted TEXT,

                resolved INTEGER DEFAULT 0,
                investigation_duration_seconds REAL,
                recurrence_count INTEGER DEFAULT 1
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS incident_families (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,

                -- Fingerprint used to match future incidents to this family
                anomaly_names TEXT NOT NULL DEFAULT '[]',
                metric_names TEXT NOT NULL DEFAULT '[]',

                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                occurrence_count INTEGER DEFAULT 1,

                severity TEXT NOT NULL DEFAULT 'warning',
                trend TEXT NOT NULL DEFAULT 'stable',        -- worsening | stable | recovering
                risk_level TEXT NOT NULL DEFAULT 'warning',  -- warning | elevated | high | critical
                metric_pct_change REAL DEFAULT 0.0,          -- % change from first to latest value

                -- JSON list of {detected_at, value} for trend computation
                metric_snapshots TEXT NOT NULL DEFAULT '[]'
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS incident_feedback (
                incident_id TEXT PRIMARY KEY,
                verdict TEXT NOT NULL,    -- 'correct' | 'partial' | 'incorrect'
                actual_cause TEXT,        -- filled when verdict = incorrect
                submitted_at TEXT NOT NULL
            )
        """)

        # ── Migrate existing databases ────────────────────────────────────────
        _add_column_if_missing(conn, "incidents", "family_id", "TEXT")
        _add_column_if_missing(conn, "incidents", "metric_names", "TEXT NOT NULL DEFAULT '[]'")

        conn.commit()
    logger.info("Incident memory database ready at %s", DB_PATH)


def _add_column_if_missing(conn, table: str, column: str, col_type: str):
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    except Exception:
        pass  # column already exists


# ── Incident CRUD ─────────────────────────────────────────────────────────────

def save_incident(anomalies: list[Anomaly], diagnosis: Diagnosis) -> tuple[str, dict]:
    """
    Persist a completed investigation. Returns (incident_id, family_dict).
    The family_dict contains occurrence_count, trend, risk_level, pct_change
    so loop.py can print an evolution summary without a second DB read.
    """
    incident_id = str(uuid.uuid4())[:8]

    affected_services = list({
        a.labels.get("application", a.labels.get("job", "unknown"))
        for a in anomalies
    })

    _PROMQL_KEYWORDS = {
        "rate", "increase", "irate", "delta", "sum", "avg", "max", "min",
        "count", "by", "without", "on", "group_left", "group_right",
        "histogram_quantile", "label_replace", "offset", "bool", "or",
        "and", "unless", "ignoring", "with",
    }
    metric_names: set[str] = set()
    for a in anomalies:
        tokens = set(re.findall(r'\b[a-z_][a-z0-9_]*\b', a.query.lower()))
        metric_names |= tokens - _PROMQL_KEYWORDS

    # Representative metric value for trend tracking (max across all signals)
    snapshot_value = max((a.value for a in anomalies), default=0.0)

    with _connect() as conn:
        family_id, family = _upsert_family(conn, anomalies, snapshot_value, diagnosis.root_cause, affected_services)

        conn.execute("""
            INSERT INTO incidents (
                id, detected_at, family_id,
                anomaly_names, affected_services, metric_names,
                root_cause, evidence, confidence,
                action_taken, container_restarted,
                resolved, investigation_duration_seconds
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            incident_id,
            anomalies[0].detected_at.isoformat(),
            family_id,
            json.dumps([a.rule_name for a in anomalies]),
            json.dumps(affected_services),
            json.dumps(sorted(metric_names)),
            diagnosis.root_cause,
            json.dumps(diagnosis.recommendations),
            0.85,
            diagnosis.action_taken.action_type,
            diagnosis.action_taken.target,
            1 if diagnosis.action_taken.success else 0,
            diagnosis.investigation_duration_seconds,
        ))
        conn.commit()

    logger.info("Incident %s saved to family %s", incident_id, family_id)
    return incident_id, family


def _upsert_family(conn, anomalies: list[Anomaly], snapshot_value: float, root_cause: str, affected_services: list[str]) -> tuple[str, dict]:
    """
    Find a matching family and update it, or create a new one.
    Returns (family_id, family_dict_with_computed_fields).
    """
    from aria.memory.family import (
        fingerprint_score, generate_name, extract_metric_names,
        compute_trend, compute_risk,
    )

    rows = conn.execute("SELECT * FROM incident_families").fetchall()
    families = [dict(r) for r in rows]

    best_score = 0.0
    best_family = None
    for fam in families:
        score = fingerprint_score(anomalies, fam)
        if score > best_score:
            best_score = score
            best_family = fam

    now = datetime.utcnow().isoformat()
    severity = max(anomalies, key=lambda a: 0 if a.severity == "warning" else 1).severity

    if best_family and best_score >= 0.60:
        # ── Update existing family ───────────────────────────────────────────
        family_id = best_family["id"]
        snapshots = json.loads(best_family["metric_snapshots"])
        snapshots.append({"detected_at": now, "value": snapshot_value})

        trend, pct_change = compute_trend(snapshots)
        occurrence_count = best_family["occurrence_count"] + 1
        risk = compute_risk(severity, occurrence_count, trend)

        conn.execute("""
            UPDATE incident_families
            SET last_seen = ?,
                occurrence_count = ?,
                trend = ?,
                risk_level = ?,
                metric_pct_change = ?,
                metric_snapshots = ?
            WHERE id = ?
        """, (now, occurrence_count, trend, risk, pct_change, json.dumps(snapshots), family_id))

        return family_id, {
            **best_family,
            "occurrence_count": occurrence_count,
            "trend": trend,
            "risk_level": risk,
            "metric_pct_change": pct_change,
            "last_seen": now,
        }
    else:
        # ── Create new family ────────────────────────────────────────────────
        family_id = str(uuid.uuid4())[:8]
        name = generate_name(anomalies, root_cause, affected_services)
        metric_names = sorted(extract_metric_names(anomalies))
        snapshots = [{"detected_at": now, "value": snapshot_value}]

        conn.execute("""
            INSERT INTO incident_families (
                id, name, anomaly_names, metric_names,
                first_seen, last_seen, occurrence_count,
                severity, trend, risk_level, metric_pct_change, metric_snapshots
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, 'stable', ?, 0.0, ?)
        """, (
            family_id, name,
            json.dumps([a.rule_name for a in anomalies]),
            json.dumps(metric_names),
            now, now, severity, severity,
            json.dumps(snapshots),
        ))

        return family_id, {
            "id": family_id, "name": name,
            "occurrence_count": 1, "trend": "stable",
            "risk_level": severity, "metric_pct_change": 0.0,
            "first_seen": now, "last_seen": now,
        }


def find_matching_family(anomalies: list[Anomaly]) -> dict | None:
    """
    Return the best-matching family for these anomalies, or None if no family
    scores above the 0.60 threshold. Used before investigation to give Claude
    family context (occurrences, trend, risk).
    """
    from aria.memory.family import fingerprint_score

    with _connect() as conn:
        rows = conn.execute("SELECT * FROM incident_families").fetchall()

    families = [dict(r) for r in rows]
    best_score = 0.0
    best_family = None
    for fam in families:
        score = fingerprint_score(anomalies, fam)
        if score > best_score:
            best_score = score
            best_family = fam

    return best_family if best_score >= 0.60 else None


def get_recent_incidents(limit: int = 20) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM incidents ORDER BY detected_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_incidents() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM incidents ORDER BY detected_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_all_families() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM incident_families ORDER BY last_seen DESC"
        ).fetchall()
    return [dict(r) for r in rows]


# ── Human Feedback ────────────────────────────────────────────────────────────

def submit_feedback(incident_id: str, verdict: str, actual_cause: str | None = None):
    """
    Record whether Claude's diagnosis was correct.
    verdict: 'correct' | 'partial' | 'incorrect'
    actual_cause: required when verdict == 'incorrect'
    """
    with _connect() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO incident_feedback (incident_id, verdict, actual_cause, submitted_at)
            VALUES (?, ?, ?, ?)
        """, (incident_id, verdict, actual_cause, datetime.utcnow().isoformat()))
        conn.commit()
    logger.info("Feedback recorded for incident %s: %s", incident_id, verdict)


def get_accuracy_stats() -> dict:
    """Compute Claude's diagnosis accuracy from all submitted feedback."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT verdict, COUNT(*) as n FROM incident_feedback GROUP BY verdict"
        ).fetchall()

    counts = {r["verdict"]: r["n"] for r in rows}
    total = sum(counts.values())
    correct = counts.get("correct", 0)
    partial = counts.get("partial", 0)
    incorrect = counts.get("incorrect", 0)

    return {
        "total": total,
        "correct": correct,
        "partial": partial,
        "incorrect": incorrect,
        "accuracy_pct": round(correct / total * 100, 1) if total else 0.0,
    }
