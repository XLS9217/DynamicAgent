from abc import ABC, abstractmethod
from datetime import datetime
import inspect
import json
from pathlib import Path


class WorkflowBase(ABC):

    def __init__(self):
        self._workflow_log = []
        self._caller_log = None
        self._caller_class = ""

    def _set_caller_log(self, caller_log, caller_class: str):
        self._caller_log = caller_log
        self._caller_class = caller_class

    async def execute_subflow(self, workflow_cls, *args, **kwargs):
        subflow = workflow_cls(*args, **kwargs)
        subflow._set_caller_log(self._workflow_log, self.__class__.__name__)
        return await subflow.execute()

    def _append_log(self, message: str):
        caller = inspect.stack()[1].function
        record = {
            "time": datetime.now().isoformat(),
            "workflow": self.__class__.__name__,
            "caller_workflow": self._caller_class,
            "function_name": caller,
            "message": message
        }
        if self._caller_log is not None and self._caller_class:
            self._caller_log.append(record)
            return
        self._workflow_log.append(record)

    def get_log(self) -> list[dict]:
        return self._workflow_log

    def save_jsonl(self, file_path: str | Path):
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for log in self._workflow_log:
                f.write(json.dumps(log, ensure_ascii=False) + "\n")

    @abstractmethod
    async def execute(self):
        pass
