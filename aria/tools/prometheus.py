import requests
from datetime import datetime, timedelta
from aria.tools.base import ToolResult


class PrometheusTools:
    def __init__(self, config):
        self.base_url = config.url

    def run(self, query: str, query_type: str = "instant", lookback_minutes: int = 10) -> ToolResult:
        try:
            if query_type == "instant":
                url = f"{self.base_url}/api/v1/query"
                params = {"query": query}
            else:
                end = datetime.utcnow()
                start = end - timedelta(minutes=lookback_minutes)
                url = f"{self.base_url}/api/v1/query_range"
                params = {
                    "query": query,
                    "start": start.isoformat() + "Z",
                    "end": end.isoformat() + "Z",
                    "step": "30s",
                }

            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            results = resp.json()["data"]["result"]

            if not results:
                return ToolResult("No data returned for this query — metric may not exist or threshold not breached.")

            lines = []
            for item in results[:20]:
                labels = ", ".join(f"{k}={v}" for k, v in item["metric"].items() if k != "__name__")
                if query_type == "instant":
                    lines.append(f"  [{labels}] value={item['value'][1]}")
                else:
                    values = [float(v[1]) for v in item["values"] if v[1] != "NaN"]
                    if values:
                        lines.append(f"  [{labels}] min={min(values):.3f} max={max(values):.3f} last={values[-1]:.3f}")

            return ToolResult("\n".join(lines))
        except requests.RequestException as e:
            return ToolResult(f"Prometheus unreachable: {e}", success=False)
