TOOL_DEFINITIONS = [
    {
        "name": "query_prometheus",
        "description": (
            "Query the Prometheus HTTP API to retrieve time-series metrics. "
            "Use this to investigate CPU, memory, error rates, JVM heap, or any other metric. "
            "Use 'range' query_type for trend analysis, 'instant' for current value. "
            "Always call this first to understand the scope and timeline of an anomaly."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "PromQL expression, e.g. rate(http_requests_total[5m])"
                },
                "query_type": {
                    "type": "string",
                    "enum": ["instant", "range"],
                    "description": "instant for current value, range for time series trend"
                },
                "lookback_minutes": {
                    "type": "integer",
                    "description": "For range queries: how many minutes back to look. Default 10.",
                    "default": 10
                }
            },
            "required": ["query", "query_type"]
        }
    },
    {
        "name": "query_pg_slow_queries",
        "description": (
            "Query PostgreSQL pg_stat_statements for slow queries. "
            "Call this when anomalies suggest high latency, CPU pressure, or errors that may be database-related. "
            "Returns queries ordered by mean execution time descending."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "since_minutes": {
                    "type": "integer",
                    "description": "Look back this many minutes. Default 15.",
                    "default": 15
                },
                "limit": {
                    "type": "integer",
                    "description": "Max rows to return. Default 10.",
                    "default": 10
                }
            },
            "required": []
        }
    },
    {
        "name": "get_kafka_consumer_lag",
        "description": (
            "Check Kafka consumer group lag. "
            "Call this when anomalies suggest message processing delays, queue buildup, or notification delivery failures. "
            "Returns lag per partition and total lag across consumer groups."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "group_id": {
                    "type": "string",
                    "description": "Specific consumer group ID. If omitted, checks all groups."
                }
            },
            "required": []
        }
    },
    {
        "name": "restart_docker_container",
        "description": (
            "Restart a Docker container by name. "
            "ONLY call this when you are confident a restart will resolve the issue "
            "and the container appears genuinely unhealthy (not just slow). "
            "Restart at most ONE container per investigation. "
            "This is the only autonomous remediation action available."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "container_name": {
                    "type": "string",
                    "description": "Exact name of the Docker container to restart."
                },
                "reason": {
                    "type": "string",
                    "description": "One-sentence justification for why this restart is warranted."
                }
            },
            "required": ["container_name", "reason"]
        }
    }
]
