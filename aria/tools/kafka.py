from aria.tools.base import ToolResult


class KafkaTools:
    def __init__(self, config):
        self.config = config

    def run(self, group_id: str | None = None) -> ToolResult:
        try:
            from confluent_kafka.admin import AdminClient
            from confluent_kafka import TopicPartition, Consumer

            admin = AdminClient({"bootstrap.servers": self.config.bootstrap_servers})

            # list_consumer_groups() returns a Future — call .result() to get groups
            groups_result = admin.list_consumer_groups().result()
            all_groups = [g.group_id for g in groups_result.valid]

            if not all_groups:
                return ToolResult("No consumer groups found in Kafka.")

            target_groups = [group_id] if group_id and group_id in all_groups else all_groups[:10]

            lines = []
            total_lag = 0

            for gid in target_groups:
                # Use a temporary consumer to fetch committed offsets + watermarks
                consumer = Consumer({
                    "bootstrap.servers": self.config.bootstrap_servers,
                    "group.id": gid,
                    "enable.auto.commit": False,
                })
                try:
                    # Get all partitions for this group via assignment metadata
                    cluster_metadata = consumer.list_topics(timeout=10)
                    group_lag = 0

                    for topic_name, topic_meta in cluster_metadata.topics.items():
                        if topic_name.startswith("__"):
                            continue  # skip internal Kafka topics

                        for partition_id in topic_meta.partitions:
                            tp = TopicPartition(topic_name, partition_id)
                            committed = consumer.committed([tp], timeout=5)
                            low, high = consumer.get_watermark_offsets(tp, timeout=5)

                            if committed and committed[0].offset >= 0:
                                lag = max(0, high - committed[0].offset)
                                group_lag += lag
                                if lag > 0:
                                    lines.append(
                                        f"  {gid} | {topic_name}[{partition_id}] "
                                        f"lag={lag} committed={committed[0].offset} high={high}"
                                    )

                    total_lag += group_lag
                    if group_lag == 0:
                        lines.append(f"  {gid}: no lag (all caught up)")
                finally:
                    consumer.close()

            summary = f"Total consumer lag across {len(target_groups)} group(s): {total_lag}"
            if total_lag > self.config.consumer_lag_threshold:
                summary += f" WARNING: above threshold ({self.config.consumer_lag_threshold})"

            return ToolResult(summary + "\n" + "\n".join(lines))

        except Exception as e:
            return ToolResult(f"Kafka check failed: {e}", success=False)
