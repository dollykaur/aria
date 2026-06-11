from aria.tools.base import ToolResult


class KafkaTools:
    def __init__(self, config):
        self.config = config

    def run(self, group_id: str | None = None) -> ToolResult:
        try:
            from confluent_kafka.admin import AdminClient
            from confluent_kafka import TopicPartition, Consumer

            admin = AdminClient({"bootstrap.servers": self.config.bootstrap_servers})

            groups_result = admin.list_consumer_groups()
            all_groups = [g.group_id for g in groups_result.valid]

            if not all_groups:
                return ToolResult("No consumer groups found in Kafka.")

            target_groups = [group_id] if group_id and group_id in all_groups else all_groups[:10]

            lines = []
            total_lag = 0

            for gid in target_groups:
                offsets_result = admin.list_consumer_group_offsets([gid])
                group_offsets = offsets_result[gid].result()

                if not group_offsets:
                    lines.append(f"  {gid}: no committed offsets")
                    continue

                # Get high watermarks to compute actual lag
                consumer = Consumer({
                    "bootstrap.servers": self.config.bootstrap_servers,
                    "group.id": f"aria-lag-check-{gid}",
                })
                try:
                    group_lag = 0
                    for tp, offset_meta in group_offsets.items():
                        low, high = consumer.get_watermark_offsets(
                            TopicPartition(tp.topic, tp.partition), timeout=5
                        )
                        committed = offset_meta.offset if offset_meta.offset >= 0 else low
                        lag = max(0, high - committed)
                        group_lag += lag
                        if lag > 0:
                            lines.append(f"  {gid} | {tp.topic}[{tp.partition}] lag={lag} committed={committed} high={high}")
                    total_lag += group_lag
                    if group_lag == 0:
                        lines.append(f"  {gid}: no lag (all caught up)")
                finally:
                    consumer.close()

            summary = f"Total consumer lag across {len(target_groups)} group(s): {total_lag}"
            if total_lag > self.config.consumer_lag_threshold:
                summary += f" ⚠️ ABOVE THRESHOLD ({self.config.consumer_lag_threshold})"

            return ToolResult(summary + "\n" + "\n".join(lines))

        except Exception as e:
            return ToolResult(f"Kafka check failed: {e}", success=False)
