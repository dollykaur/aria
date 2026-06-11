import time
import logging
import sys
from aria.config import load_config
from aria.detectors.prometheus import PrometheusDetector
from aria.agent.loop import investigate
from aria.notifiers.slack import SlackNotifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("aria")


def main():
    config = load_config()
    detector = PrometheusDetector(config.prometheus)
    notifier = SlackNotifier(config.slack)

    logger.info("ARIA started — polling every %ds", config.prometheus.poll_interval_seconds)
    logger.info("Model: %s | Max iterations: %d", config.claude_model, config.max_tool_iterations)

    while True:
        try:
            anomalies = detector.check()
            if anomalies:
                logger.info("Detected %d anomaly(ies) — starting investigation", len(anomalies))
                diagnosis = investigate(anomalies, config)
                notifier.post(diagnosis)
                logger.info("Investigation complete: %s", diagnosis.root_cause)
            else:
                logger.debug("All clear")
        except KeyboardInterrupt:
            logger.info("ARIA shutting down")
            break
        except Exception:
            logger.exception("Unexpected error in polling loop — continuing")

        time.sleep(config.prometheus.poll_interval_seconds)


if __name__ == "__main__":
    main()
