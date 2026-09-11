"""Filesystem access for cache-backed logs."""

import asyncio
import os
from pathlib import Path
from typing import ClassVar

import aiofiles

from dynamic_agent_service.logging.log_struct import InvokeLog


class CacheLogAccessor:
    """Own cache-log paths and all filesystem operations for logs."""

    cache_log_root: ClassVar[Path] = Path(
        os.getenv("CACHE_DIR") or ".cache"
    ).resolve()
    _trigger_locks: ClassVar[dict[str, asyncio.Lock]] = {}

    @classmethod
    def configure_root(cls, root: str | Path) -> None:
        cls.cache_log_root = Path(root).resolve()

    @classmethod
    async def append_invoke_log(cls, log: InvokeLog) -> None:
        file_id = log.trigger_id or log.invoke_id
        log_dir = cls.cache_log_root / "trigger_log"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{file_id}.jsonl"
        lock = cls._trigger_locks.setdefault(file_id, asyncio.Lock())
        async with lock:
            async with aiofiles.open(log_file, mode="a", encoding="utf-8") as file:
                await file.write(log.model_dump_json() + "\n")
