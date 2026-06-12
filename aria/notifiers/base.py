# abc = Abstract Base Classes — Python's built-in module for defining interfaces.
# ABC means "this class cannot be used directly, only subclassed."
# abstractmethod means "every subclass MUST implement this method."
from abc import ABC, abstractmethod
from aria.models import Diagnosis


class BaseNotifier(ABC):
    """Every notifier (Slack, Email, Console) must implement this one method."""

    @abstractmethod
    def post(self, diagnosis: Diagnosis) -> None:
        pass
