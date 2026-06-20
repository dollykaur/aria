import os
import yaml
from pathlib import Path
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()


class PrometheusConfig(BaseModel):
    url: str = "http://localhost:9090"
    poll_interval_seconds: int = 30
    anomaly_rules: list[dict] = []


class PostgresConfig(BaseModel):
    host: str = "localhost"
    port: int = 5432
    database: str = "notifications"
    user: str = "notif_user"
    password: str = ""
    slow_query_threshold_ms: int = 500


class KafkaConfig(BaseModel):
    bootstrap_servers: str = "localhost:9092"
    enabled: bool = True
    consumer_lag_threshold: int = 1000


class SlackConfig(BaseModel):
    webhook_url: str = ""


class EmailConfig(BaseModel):
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    email_sender: str = ""
    email_password: str = ""
    email_recipient: str = ""


class DockerConfig(BaseModel):
    safe_containers: list[str] = []
    socket_url: str = "unix:///var/run/docker.sock"


class AriaConfig(BaseModel):
    prometheus: PrometheusConfig
    postgres: PostgresConfig
    kafka: KafkaConfig
    slack: SlackConfig
    email: EmailConfig
    docker: DockerConfig
    # "slack", "email", or "console" — user picks one
    notifier: str = "console"
    anthropic_api_key: str
    claude_model: str = "claude-sonnet-4-6"
    max_tool_iterations: int = 10
    investigation_timeout_seconds: int = 120


def load_config(config_path: str | None = None) -> AriaConfig:
    path = Path(config_path or Path(__file__).parent / "config.yaml")
    raw = yaml.safe_load(path.read_text()) if path.exists() else {}

    pg_raw = raw.get("postgres", {})
    kafka_raw = raw.get("kafka", {})
    docker_raw = raw.get("docker", {})
    email_raw = raw.get("email", {})

    return AriaConfig(
        prometheus=PrometheusConfig(**raw.get("prometheus", {})),
        postgres=PostgresConfig(
            host=os.getenv("ARIA_PG_HOST", pg_raw.get("host", "localhost")),
            port=int(os.getenv("ARIA_PG_PORT", pg_raw.get("port", 5432))),
            database=os.getenv("ARIA_PG_DATABASE", pg_raw.get("database", "notifications")),
            user=os.getenv("ARIA_PG_USER", pg_raw.get("user", "notif_user")),
            password=os.getenv("ARIA_PG_PASSWORD", pg_raw.get("password", "")),
            slow_query_threshold_ms=pg_raw.get("slow_query_threshold_ms", 500),
        ),
        kafka=KafkaConfig(
            bootstrap_servers=os.getenv("ARIA_KAFKA_BOOTSTRAP_SERVERS", kafka_raw.get("bootstrap_servers", "localhost:9092")),
            enabled=os.getenv("ARIA_KAFKA_ENABLED", str(kafka_raw.get("enabled", True))).lower() == "true",
            consumer_lag_threshold=kafka_raw.get("consumer_lag_threshold", 1000),
        ),
        slack=SlackConfig(
            webhook_url=os.getenv("ARIA_SLACK_WEBHOOK_URL", ""),
        ),
        email=EmailConfig(
            smtp_host=os.getenv("ARIA_SMTP_HOST", email_raw.get("smtp_host", "smtp.gmail.com")),
            smtp_port=int(os.getenv("ARIA_SMTP_PORT", email_raw.get("smtp_port", 465))),
            email_sender=os.getenv("ARIA_EMAIL_SENDER", email_raw.get("email_sender", "")),
            email_password=os.getenv("ARIA_EMAIL_PASSWORD", email_raw.get("email_password", "")),
            email_recipient=os.getenv("ARIA_EMAIL_RECIPIENT", email_raw.get("email_recipient", "")),
        ),
        docker=DockerConfig(
            safe_containers=docker_raw.get("safe_containers", []),
            socket_url=docker_raw.get("socket_url", "unix:///var/run/docker.sock"),
        ),
        # ARIA_NOTIFIER env var wins over config.yaml, which wins over default ("console")
        notifier=os.getenv("ARIA_NOTIFIER", raw.get("notifier", "console")),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        claude_model=os.getenv("ARIA_CLAUDE_MODEL", raw.get("claude_model", "claude-sonnet-4-6")),
        max_tool_iterations=raw.get("max_tool_iterations", 10),
        investigation_timeout_seconds=raw.get("investigation_timeout_seconds", 120),
    )
