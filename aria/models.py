from pydantic import BaseModel
from datetime import datetime
from enum import Enum


class Severity(str, Enum):
    WARNING = "warning"
    CRITICAL = "critical"


class Anomaly(BaseModel):
    rule_name: str
    query: str
    value: float
    severity: Severity
    detected_at: datetime
    labels: dict[str, str] = {}


class ActionTaken(BaseModel):
    action_type: str  # "restart_container" | "none"
    target: str | None = None
    success: bool
    detail: str


class CorrelatedIncident(BaseModel):
    title: str               # "Fleet-wide High CPU Usage" or just the rule name
    severity: Severity       # highest severity across the group
    anomalies: list[Anomaly]
    affected_services: list[str]  # service names extracted from Prometheus labels


class Diagnosis(BaseModel):
    anomalies: list[Anomaly]
    root_cause: str
    recommendations: list[str]
    action_taken: ActionTaken
    investigation_duration_seconds: float
