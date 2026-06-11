import docker
from aria.tools.base import ToolResult


class DockerTools:
    def __init__(self, config):
        self.config = config
        self._client = None

    def _get_client(self):
        if self._client is None:
            self._client = docker.DockerClient(base_url=self.config.socket_url)
        return self._client

    def run(self, container_name: str, reason: str) -> ToolResult:
        if container_name not in self.config.safe_containers:
            return ToolResult(
                f"REFUSED: '{container_name}' is not in the approved list: {self.config.safe_containers}. "
                "Update docker.safe_containers in config.yaml to allow this.",
                success=False,
            )

        try:
            client = self._get_client()
            container = client.containers.get(container_name)
            container.restart(timeout=30)
            return ToolResult(f"Successfully restarted '{container_name}'. Reason: {reason}")
        except docker.errors.NotFound:
            return ToolResult(f"Container '{container_name}' not found — it may not be running.", success=False)
        except Exception as e:
            return ToolResult(f"Restart failed for '{container_name}': {e}", success=False)
