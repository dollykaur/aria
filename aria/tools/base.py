from dataclasses import dataclass


@dataclass
class ToolResult:
    content: str
    success: bool = True


class _DisabledTool:
    def __init__(self, name: str):
        self._name = name

    def run(self, **kwargs) -> ToolResult:
        return ToolResult(f"{self._name} is disabled in config — skipping.", success=True)


class ToolRegistry:
    def __init__(self, config):
        from aria.tools.prometheus import PrometheusTools
        from aria.tools.postgres import PostgresTools
        from aria.tools.kafka import KafkaTools
        from aria.tools.docker_tool import DockerTools

        self._tools = {
            "query_prometheus": PrometheusTools(config.prometheus),
            "query_pg_slow_queries": PostgresTools(config.postgres),
            "get_kafka_consumer_lag": KafkaTools(config.kafka) if config.kafka.enabled else _DisabledTool("Kafka"),
            "restart_docker_container": DockerTools(config.docker),
        }

    def execute(self, name: str, inputs: dict) -> ToolResult:
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(f"Unknown tool: {name}", success=False)
        try:
            return tool.run(**inputs)
        except Exception as e:
            return ToolResult(f"Tool error ({name}): {e}", success=False)
