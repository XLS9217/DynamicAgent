import json
import os
from pathlib import Path
from dotenv import load_dotenv
import aiofiles
from datetime import UTC, datetime
import asyncio

load_dotenv()


class SessionLogger:

    def __init__(self, session_id: str):
        self.session_id = session_id
        cache_folder = os.getenv("CACHE_DIR") or ".cache"
        self.log_dir = Path(cache_folder) / "session_log" / session_id
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            self.log_dir = Path.cwd() / ".cache" / "session_log" / session_id
            self.log_dir.mkdir(parents=True, exist_ok=True)
        self._current_trigger_file: str | None = None
        self._current_invoke: dict | None = None
        self._invoke_index = 0
        self._write_queue = asyncio.Queue()
        self._writer_task = None

    async def _writer_loop(self):
        """Background task that processes write queue."""
        while True:
            file, line = await self._write_queue.get()
            try:
                log_file = self.log_dir / f"{file}.jsonl"
                timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
                line_with_timestamp = {"timestamp": timestamp, **line}
                async with aiofiles.open(log_file, mode="a", encoding="utf-8") as f:
                    await f.write(json.dumps(line_with_timestamp, ensure_ascii=False) + "\n")
            except Exception as e:
                print(f"Error writing log: {e}")
            finally:
                self._write_queue.task_done()

    def _ensure_writer(self):
        """Ensure writer task is running."""
        if self._writer_task is None or self._writer_task.done():
            self._writer_task = asyncio.create_task(self._writer_loop())

    def _write(self, file: str, line: dict):
        """Fire-and-forget write to a file."""
        self._ensure_writer()
        self._write_queue.put_nowait((file, line))

    # --- System-level logging (session_system_log.jsonl) ---

    def log_system(self, event: str, data: dict = None):
        """Log a lifecycle/system event to session_system_log.jsonl."""
        line = {"event": event}
        if data:
            line["data"] = data
        self._write("session_system_log", line)

    # --- Trigger logging (one file per trigger, one line per LLM invoke) ---

    def trigger_new(self) -> str:
        """Start a trigger file and close any incomplete previous trigger."""
        self.trigger_complete()
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
        self._current_trigger_file = f"trigger_{ts}"
        self._invoke_index = 0
        return self._current_trigger_file

    def invoke_new(self) -> None:
        """Start a new invoke record, flushing the previous invoke as one line."""
        self._flush_current_invoke()
        if self._current_trigger_file is None:
            self.trigger_new()
        self._invoke_index += 1
        self._current_invoke = {
            "invoke": self._invoke_index,
            "events": [],
        }

    def invoke_log(self, line: dict):
        """Append an event to the current invoke record."""
        if self._current_invoke is not None:
            self._current_invoke["events"].append(line)

    def trigger_complete(self) -> None:
        """Flush the final invoke and close the current trigger file."""
        self._flush_current_invoke()
        self._current_trigger_file = None

    def _flush_current_invoke(self) -> None:
        if self._current_trigger_file and self._current_invoke is not None:
            self._write(self._current_trigger_file, self._current_invoke)
        self._current_invoke = None
