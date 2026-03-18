from abc import ABC


class WorkflowBase(ABC):

    def _append_log(self, message:dict):
        """Log a message related to the workflow."""
        print(f"Workflow Log: {message}")

    def get_log(self):
        pass

    def __init__(self):
        self._workflow_log = [] # the reason I do this is it can be easily converted to jsonl or json
        pass