import time
import logging
import sys
from aria.config import load_config
from aria.detectors.prometheus import PrometheusDetector
from aria.agent.loop import investigate
from aria.notifiers.factory import build_notifier
from anthropic import AuthenticationError, BadRequestError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("aria")


def main():
    config = load_config()
    detector = PrometheusDetector(config.prometheus)
    notifier = build_notifier(config)

    logger.info("ARIA started — polling every %ds", config.prometheus.poll_interval_seconds)
    logger.info("Model: %s | Notifier: %s | Max iterations: %d", config.claude_model, config.notifier, config.max_tool_iterations)

    while True:
        try:
            anomalies = detector.check()
            if anomalies:
                print(f"\n{'='*60}")
                print(f"ARIA detected {len(anomalies)} anomaly(ies) — investigating...")
                for a in anomalies:
                    print(f"  • [{a.severity.upper()}] {a.rule_name}")
                print(f"{'='*60}")
                diagnosis = investigate(anomalies, config)
                notifier.post(diagnosis)
            else:
                logger.debug("All clear")
        except KeyboardInterrupt:
            logger.info("ARIA shutting down")
            break
        except AuthenticationError:
            logger.error("Invalid Anthropic API key — check ANTHROPIC_API_KEY in your .env file")
            break
        except BadRequestError as e:
            if "credit balance is too low" in str(e):
                logger.error(
                    "Your Anthropic account has no credits. "
                    "Add credits at https://console.anthropic.com/settings/billing and restart ARIA."
                )
            else:
                logger.error("Claude API rejected the request: %s", e)
        except Exception:
            logger.exception("Unexpected error in polling loop — continuing")

        time.sleep(config.prometheus.poll_interval_seconds)


if __name__ == "__main__":
    main()
