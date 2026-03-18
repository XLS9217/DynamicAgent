from abc import ABC, abstractmethod
from datetime import datetime
import inspect
import json
from pathlib import Path


class WorkflowBase(ABC):

    def __init__(self):
        self._workflow_log = []
        self._caller_append_log = None

    def _set_caller_append_log(self, caller_append_log):
        self._caller_append_log = caller_append_log

    async def execute_subflow(self, workflow_cls, *args, **kwargs):
        subflow = workflow_cls(*args, **kwargs)
        subflow._set_caller_append_log(self._append_log)
        return await subflow.execute()

    def _append_log(self, message: str):
        caller = inspect.stack()[1].function
        record = {
            "workflow": self.__class__.__name__,
            "function_name": caller,
            "time": datetime.now().isoformat(),
            "message": message
        }
        self._workflow_log.append(record)
        if self._caller_append_log is not None:
            self._caller_append_log(f"[{record['workflow']}.{record['function_name']}] {message}")

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
