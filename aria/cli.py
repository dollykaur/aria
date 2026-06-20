"""
CLI entry points for human-in-the-loop feedback and statistics.

  aria feedback <incident_id> correct
  aria feedback <incident_id> partial
  aria feedback <incident_id> incorrect "the actual root cause"

  aria stats
"""
import sys
from aria.memory.store import submit_feedback, get_accuracy_stats, get_all_families


def feedback_main():
    """
    aria-feedback entry point.
    Usage: aria feedback <id> correct|partial|incorrect [actual cause]
    """
    args = sys.argv[1:]

    if len(args) < 2:
        print("Usage: aria feedback <incident_id> correct|partial|incorrect [actual cause]")
        sys.exit(1)

    incident_id = args[0]
    verdict = args[1].lower()

    if verdict not in ("correct", "partial", "incorrect"):
        print(f"Invalid verdict '{verdict}'. Must be: correct | partial | incorrect")
        sys.exit(1)

    actual_cause = " ".join(args[2:]) if len(args) > 2 else None

    if verdict == "incorrect" and not actual_cause:
        print("For 'incorrect' verdicts, provide the actual cause:")
        print(f'  aria feedback {incident_id} incorrect "database lock contention"')
        sys.exit(1)

    submit_feedback(incident_id, verdict, actual_cause)

    print(f"Feedback recorded for incident {incident_id}: {verdict}")
    if actual_cause:
        print(f"Actual cause: {actual_cause}")


def stats_main():
    """
    aria-stats entry point.
    Prints Claude accuracy and all active incident families.
    """
    acc = get_accuracy_stats()
    families = get_all_families()

    print("\nARIA Diagnosis Accuracy")
    print("=" * 40)
    if acc["total"] == 0:
        print("No feedback submitted yet.")
        print("After each investigation, run:")
        print("  aria feedback <incident_id> correct|partial|incorrect")
    else:
        print(f"Diagnoses reviewed : {acc['total']}")
        print(f"  Correct          : {acc['correct']}  ({acc['accuracy_pct']}%)")
        print(f"  Partial          : {acc['partial']}")
        print(f"  Incorrect        : {acc['incorrect']}")

    print("\nIncident Families")
    print("=" * 40)
    if not families:
        print("No families yet — run ARIA to start building history.")
    else:
        for fam in families:
            pct = abs(fam.get("metric_pct_change", 0.0))
            pct_str = (
                f"  {'+' if fam['metric_pct_change'] > 0 else '-'}{pct:.0f}% metric"
                if pct > 5 else ""
            )
            first = fam["first_seen"][:16].replace("T", " ")
            last = fam["last_seen"][:16].replace("T", " ")
            print(
                f"  {fam['name']:<30} "
                f"{fam['occurrence_count']:>2} occurrence(s)  "
                f"{fam['trend'].upper():<12} "
                f"Risk: {fam['risk_level'].upper():<8}"
                f"{pct_str}"
            )
            print(f"    First: {first}  |  Last: {last}")
    print()
