"""Filesystem access for cache-backed logs."""

import asyncio
import json
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
    max_log_bytes: ClassVar[int] = 2 * 1024 * 1024
    log_suffixes: ClassVar[set[str]] = {".jsonl", ".log", ".md"}
    _trigger_locks: ClassVar[dict[str, asyncio.Lock]] = {}

    @classmethod
    def configure_root(cls, root: str | Path) -> None:
        cls.cache_log_root = Path(root).resolve()

    @classmethod
    def list_log_files(cls) -> list[dict]:
        if not cls.cache_log_root.exists():
            return []

        files = []
        for path in cls.cache_log_root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in cls.log_suffixes:
                continue
            stat = path.stat()
            relative_path = path.relative_to(cls.cache_log_root).as_posix()
            parts = relative_path.split("/")
            files.append({
                "path": relative_path,
                "name": path.name,
                "category": parts[0] if len(parts) > 1 else "system",
                "format": "jsonl" if path.suffix.lower() == ".jsonl" else "text",
                "size": stat.st_size,
                "modified_at": stat.st_mtime,
            })
        return sorted(files, key=lambda item: item["modified_at"], reverse=True)

    @classmethod
    def resolve_log_path(cls, relative_path: str) -> Path:
        path = (cls.cache_log_root / relative_path).resolve()
        if (
            not path.is_relative_to(cls.cache_log_root)
            or not path.is_file()
            or path.suffix.lower() not in cls.log_suffixes
        ):
            raise FileNotFoundError(relative_path)
        return path

    @classmethod
    async def read_log_file(cls, relative_path: str) -> dict:
        path = cls.resolve_log_path(relative_path)
        size = path.stat().st_size
        async with aiofiles.open(
            path,
            mode="r",
            encoding="utf-8",
            errors="replace",
        ) as file:
            content = await file.read(cls.max_log_bytes)

        if path.suffix.lower() == ".jsonl":
            entries = []
            for line in content.splitlines():
                if not line.strip():
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    entries.append({"raw": line})
            return {
                "path": relative_path,
                "format": "jsonl",
                "entries": entries,
                "truncated": size > cls.max_log_bytes,
            }

        return {
            "path": relative_path,
            "format": "text",
            "content": content,
            "truncated": size > cls.max_log_bytes,
        }

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

    @classmethod
    async def clear_system_log(cls) -> bool:
        path = cls.cache_log_root / "system.log"
        if not path.is_file():
            return False
        async with aiofiles.open(path, mode="w", encoding="utf-8"):
            pass
        return True
