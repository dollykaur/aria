from aria.models import Diagnosis
from aria.notifiers.base import BaseNotifier


class ConsoleNotifier(BaseNotifier):
    """Prints the diagnosis directly to the terminal. Useful for local development."""

    def post(self, diagnosis: Diagnosis) -> None:
        print("\n" + "=" * 60)
        print("ARIA DIAGNOSIS")
        print("=" * 60)

        for a in diagnosis.anomalies:
            print(f"[{a.severity.upper()}] {a.rule_name}: {a.value:.4f}")

        print(f"\nROOT CAUSE:\n  {diagnosis.root_cause}")

        if diagnosis.recommendations:
            print("\nRECOMMENDATIONS:")
            for r in diagnosis.recommendations:
                print(f"  - {r}")

        print(f"\nACTION TAKEN: {diagnosis.action_taken.detail}")
        print(f"Duration: {diagnosis.investigation_duration_seconds}s")
        print("=" * 60 + "\n")
