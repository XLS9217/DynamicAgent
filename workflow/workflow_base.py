from abc import ABC, abstractmethod
from datetime import datetime
import inspect
import json
import os
from pathlib import Path
import shutil
from dotenv import load_dotenv
from dynamic_agent_service.agent.language_engine import LanguageEngine
from dynamic_agent_service.agent.vision_engine import VisionEngine


async def build_workflow(
    workflow_cls,
    *args,
    workflow_bucket: str | Path | None = None,
    **kwargs
):
    load_dotenv()
    language_engine = LanguageEngine(
        api_key=os.getenv("LLM_API_KEY"),
        base_url=os.getenv("LLM_BASE_URL"),
        model=os.getenv("LLM_NAME")
    )
    vision_engine = VisionEngine(
        api_key=os.getenv("VLM_API_KEY"),
        base_url=os.getenv("VLM_BASE_URL"),
        model=os.getenv("VLM_NAME")
    )
    if workflow_bucket is None:
        cache_dir = os.getenv("CACHE_DIR")
        log_name = f"{workflow_cls.__name__}.jsonl"
        if cache_dir:
            workflow_bucket = Path(cache_dir) / log_name
        else:
            workflow_bucket = Path.cwd() / log_name
    else:
        workflow_bucket = Path(workflow_bucket)
    workflow_bucket.parent.mkdir(parents=True, exist_ok=True)
    with open(workflow_bucket, "w", encoding="utf-8") as f:
        f.write("")

    workflow = workflow_cls()
    workflow._language_engine = language_engine
    workflow._vision_engine = vision_engine
    workflow._workflow_bucket = workflow_bucket
    await workflow.build(*args, **kwargs)
    return workflow


class WorkflowBase(ABC):

    def __init__(self):
        self._workflow_bucket = None
        self._caller_class = ""
        self._language_engine = None
        self._vision_engine = None

    async def build(self, *args, **kwargs):
        return self

    async def execute_subflow(self, workflow_cls, *args, **kwargs):
        subflow = workflow_cls()
        subflow._language_engine = self._language_engine
        subflow._vision_engine = self._vision_engine
        subflow._workflow_bucket = self._workflow_bucket
        subflow._caller_class = self.__class__.__name__
        await subflow.build(*args, **kwargs)
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
        path = self._workflow_bucket
        if path is None:
            load_dotenv()
            cache_dir = os.getenv("CACHE_DIR")
            log_name = f"{self.__class__.__name__}.jsonl"
            if cache_dir:
                path = Path(cache_dir) / log_name
            else:
                path = Path.cwd() / log_name
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.touch()
            self._workflow_bucket = path
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def get_log(self) -> list[dict]:
        if self._workflow_bucket is None or not self._workflow_bucket.exists():
            return []
        logs = []
        with open(self._workflow_bucket, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                logs.append(json.loads(line))
        return logs

    def save_jsonl(self, file_path: str | Path):
        if self._workflow_bucket is None:
            return
        source = self._workflow_bucket
        target = Path(file_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() == target.resolve():
            return
        shutil.copyfile(source, target)

    @abstractmethod
    async def execute(self):
        pass
