from abc import ABC, abstractmethod
from typing import List

class BaseScheduler(ABC):
    @abstractmethod
    def get_cron_jobs(self) -> List:
        """
        Define cron-like periodic tasks for the arq worker.
        """
        pass
