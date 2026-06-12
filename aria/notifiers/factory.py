from aria.notifiers.base import BaseNotifier


def build_notifier(config) -> BaseNotifier:
    """
    Reads config.notifier and returns the matching notifier instance.
    The rest of the app doesn't need to know which one — it just calls .post().
    This pattern is called a Factory — one function that decides which object to create.
    """
    choice = config.notifier.lower()

    if choice == "slack":
        from aria.notifiers.slack import SlackNotifier
        return SlackNotifier(config.slack)

    elif choice == "email":
        from aria.notifiers.email import EmailNotifier
        return EmailNotifier(config.email)

    elif choice == "console":
        from aria.notifiers.console import ConsoleNotifier
        return ConsoleNotifier()

    else:
        raise ValueError(
            f"Unknown notifier '{choice}'. "
            "Set ARIA_NOTIFIER to one of: slack, email, console"
        )
