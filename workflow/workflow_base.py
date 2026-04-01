"""
Base class for all workflows providing LLM invocation, logging, and subflow execution.

Provides the shared infrastructure every workflow depends on: language engine and vision
engine access, JSONL-based structured logging, and subflow composition. The build_workflow()
factory handles engine initialization from environment variables and log file setup.
Workflows are composed by calling execute_subflow(), which shares engines and log bucket
with child workflows.
"""
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

    def _resolve_bucket(self) -> Path:
        if self._workflow_bucket is not None:
            return self._workflow_bucket
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
        return path

    def _build_log(self, category: str, caller: str, **extra) -> dict:
        record = {
            "time": datetime.now().isoformat(),
            "category": category,
            "workflow": self.__class__.__name__,
            "caller_workflow": self._caller_class,
            "function_name": caller,
            **extra
        }
        return record

    def _write_log(self, record: dict):
        path = self._resolve_bucket()
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def append_log(self, message: str):
        caller = inspect.stack()[1].function
        record = self._build_log("SYSTEM", caller, message=message)
        self._write_log(record)

    @staticmethod
    def _strip_images(messages: list) -> list:
        stripped = []
        for msg in messages:
            if isinstance(msg.get("content"), list):
                text_parts = [p for p in msg["content"] if p.get("type") != "image_url"]
                stripped.append({**msg, "content": text_parts})
            else:
                stripped.append(msg)
        return stripped

    @staticmethod
    def _has_images(messages: list) -> bool:
        for msg in messages:
            if isinstance(msg.get("content"), list):
                if any(p.get("type") == "image_url" for p in msg["content"]):
                    return True
        return False

    async def invoke_agent(self, messages: list, images: list = None) -> str:
        caller = inspect.stack()[1].function
        use_vision = images or self._has_images(messages)

        log_messages = self._strip_images(messages)
        record = self._build_log("AGENT", caller, messages=log_messages)
        self._write_log(record)

        if use_vision:
            response = await self._vision_engine.async_get_response(messages, images or [])
        else:
            response = await self._language_engine.async_get_response(messages)

        response_record = self._build_log("AGENT", caller, message=response)
        self._write_log(response_record)
        return response

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
