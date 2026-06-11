import psycopg2
from aria.tools.base import ToolResult


class PostgresTools:
    def __init__(self, config):
        self.config = config

    def run(self, since_minutes: int = 15, limit: int = 10) -> ToolResult:
        try:
            conn = psycopg2.connect(
                host=self.config.host,
                port=self.config.port,
                dbname=self.config.database,
                user=self.config.user,
                password=self.config.password,
                connect_timeout=10,
            )
            try:
                with conn.cursor() as cur:
                    # Check if pg_stat_statements extension is available
                    cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements'")
                    if not cur.fetchone():
                        return ToolResult("pg_stat_statements extension not enabled — cannot retrieve slow queries.")

                    cur.execute("""
                        SELECT query, calls, mean_exec_time, max_exec_time, total_exec_time, rows
                        FROM pg_stat_statements
                        WHERE mean_exec_time > %s
                        ORDER BY mean_exec_time DESC
                        LIMIT %s
                    """, (self.config.slow_query_threshold_ms, limit))
                    rows = cur.fetchall()
            finally:
                conn.close()

            if not rows:
                return ToolResult(f"No slow queries found (threshold: {self.config.slow_query_threshold_ms}ms). Database appears healthy.")

            lines = [f"Slow queries (>{self.config.slow_query_threshold_ms}ms):"]
            for q, calls, mean_ms, max_ms, total_ms, row_count in rows:
                short_q = q[:120].replace("\n", " ")
                lines.append(f"  mean={mean_ms:.1f}ms max={max_ms:.1f}ms calls={calls} rows={row_count} | {short_q}")

            return ToolResult("\n".join(lines))
        except psycopg2.OperationalError as e:
            return ToolResult(f"PostgreSQL connection failed: {e}", success=False)
