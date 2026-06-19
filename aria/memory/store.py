# sqlite3 is Python's built-in database library.
# No installation needed — it ships with Python.
# SQLite stores everything in a single file (incidents.db) on disk.
import sqlite3
import json
import uuid
import logging
from datetime import datetime
from pathlib import Path
from aria.models import Anomaly, Diagnosis

logger = logging.getLogger(__name__)

# The database file lives inside the memory/ folder
DB_PATH = Path(__file__).parent / "incidents.db"


def _connect() -> sqlite3.Connection:
    """Open a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    # Row factory makes rows behave like dicts instead of plain tuples
    # so we can access columns by name: row["root_cause"] instead of row[3]
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """
    Create the incidents table if it doesn't exist yet.
    Called once at ARIA startup.
    """
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS incidents (
                id TEXT PRIMARY KEY,
                detected_at TEXT NOT NULL,
                resolved_at TEXT,

                -- What happened (stored as JSON lists)
                anomaly_names TEXT NOT NULL,
                affected_services TEXT NOT NULL,

                -- What ARIA found
                root_cause TEXT NOT NULL,
                evidence TEXT NOT NULL,
                confidence REAL DEFAULT 0.0,

                -- What was done
                action_taken TEXT NOT NULL,
                container_restarted TEXT,

                -- Outcome
                resolved INTEGER DEFAULT 0,
                investigation_duration_seconds REAL,
                recurrence_count INTEGER DEFAULT 1
            )
        """)
        conn.commit()
    logger.info("Incident memory database ready at %s", DB_PATH)


def save_incident(anomalies: list[Anomaly], diagnosis: Diagnosis):
    """Save a completed investigation to the database."""
    incident_id = str(uuid.uuid4())[:8]  # short readable ID like "a3f9b2c1"

    # Extract unique service names from anomaly labels
    affected_services = list({
        a.labels.get("application", a.labels.get("job", "unknown"))
        for a in anomalies
    })

    with _connect() as conn:
        conn.execute("""
            INSERT INTO incidents (
                id, detected_at, anomaly_names, affected_services,
                root_cause, evidence, confidence, action_taken,
                container_restarted, resolved, investigation_duration_seconds
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            incident_id,
            anomalies[0].detected_at.isoformat(),
            # Store lists as JSON strings — SQLite doesn't have array types
            json.dumps([a.rule_name for a in anomalies]),
            json.dumps(affected_services),
            diagnosis.root_cause,
            json.dumps(diagnosis.recommendations),
            0.85,  # default confidence — will improve with verifier agent in v3
            diagnosis.action_taken.action_type,
            diagnosis.action_taken.target,
            1 if diagnosis.action_taken.success else 0,
            diagnosis.investigation_duration_seconds,
        ))
        conn.commit()

    logger.info("Incident %s saved to memory", incident_id)
    return incident_id


def get_recent_incidents(limit: int = 20) -> list[dict]:
    """Fetch the most recent incidents for similarity matching."""
    with _connect() as conn:
        rows = conn.execute("""
            SELECT * FROM incidents
            ORDER BY detected_at DESC
            LIMIT ?
        """, (limit,)).fetchall()

    return [dict(row) for row in rows]


def get_all_incidents() -> list[dict]:
    """Fetch all incidents — used for reporting and stats."""
    with _connect() as conn:
        rows = conn.execute("""
            SELECT * FROM incidents ORDER BY detected_at DESC
        """).fetchall()
    return [dict(row) for row in rows]
