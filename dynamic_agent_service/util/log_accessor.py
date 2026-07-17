import json
import os
import asyncio
from pathlib import Path

import aiofiles


MAX_LOG_BYTES = 2 * 1024 * 1024
LOG_SUFFIXES = {".jsonl", ".log", ".md"}


def get_log_root() -> Path:
    return Path(os.getenv("CACHE_DIR") or ".cache").resolve()


def list_log_files() -> list[dict]:
    root = get_log_root()
    if not root.exists():
        return []

    files = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in LOG_SUFFIXES:
            continue
        stat = path.stat()
        relative_path = path.relative_to(root).as_posix()
        parts = relative_path.split("/")
        files.append({
            "path": relative_path,
            "name": path.name,
            "category": parts[0] if len(parts) > 1 else "system",
            "session_id": parts[1] if len(parts) > 2 and parts[0] == "session_log" else None,
            "format": "jsonl" if path.suffix.lower() == ".jsonl" else "text",
            "size": stat.st_size,
            "modified_at": stat.st_mtime,
        })
    return sorted(files, key=lambda item: item["modified_at"], reverse=True)


def resolve_log_path(relative_path: str) -> Path:
    root = get_log_root()
    path = (root / relative_path).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() not in LOG_SUFFIXES:
        raise FileNotFoundError(relative_path)
    return path


async def read_log_file(relative_path: str) -> dict:
    path = resolve_log_path(relative_path)
    size = path.stat().st_size
    async with aiofiles.open(path, mode="r", encoding="utf-8", errors="replace") as file:
        content = await file.read(MAX_LOG_BYTES)

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
            "truncated": size > MAX_LOG_BYTES,
        }

    return {
        "path": relative_path,
        "format": "text",
        "content": content,
        "truncated": size > MAX_LOG_BYTES,
    }


async def clear_system_log() -> bool:
    path = get_log_root() / "system.log"
    if not path.is_file():
        return False
    async with aiofiles.open(path, mode="w", encoding="utf-8"):
        pass
    return True


async def clear_session_logs(session_id: str) -> int:
    session_root = (get_log_root() / "session_log").resolve()
    session_dir = (session_root / session_id).resolve()
    if not session_dir.is_relative_to(session_root) or not session_dir.is_dir():
        return 0

    log_files = [
        path
        for path in session_dir.iterdir()
        if path.is_file() and path.suffix.lower() in LOG_SUFFIXES
    ]
    for path in log_files:
        await asyncio.to_thread(path.unlink)
    return len(log_files)
