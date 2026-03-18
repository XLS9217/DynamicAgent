from abc import ABC, abstractmethod
from datetime import datetime
import inspect


class WorkflowBase(ABC):

    def __init__(self):
        self._workflow_log = []

    def _append_log(self, message: str):
        caller = inspect.stack()[1].function
        self._workflow_log.append({
            "function_name": caller,
            "time": datetime.now().isoformat(),
            "message": message
        })

    def get_log(self) -> list[dict]:
        return self._workflow_log

    @abstractmethod
    async def execute(self):
        pass