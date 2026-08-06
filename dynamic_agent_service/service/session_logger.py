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
        self._current_invokes: dict[str, dict] = {}
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

    def invoke_new(
        self,
        runner_id: str = "main",
        runner_name: str = "main",
        parent_runner_id: str | None = None,
    ) -> None:
        """Start an invoke record for one runner within the current trigger."""
        self._flush_current_invoke(runner_id)
        if self._current_trigger_file is None:
            self.trigger_new()
        self._invoke_index += 1
        self._current_invokes[runner_id] = {
            "invoke": self._invoke_index,
            "runner_id": runner_id,
            "runner_name": runner_name,
            "parent_runner_id": parent_runner_id,
            "events": [],
        }

    def invoke_log(self, line: dict, runner_id: str = "main"):
        """Append an event to the current invoke record for a runner."""
        current_invoke = self._current_invokes.get(runner_id)
        if current_invoke is not None:
            current_invoke["events"].append(line)

    def trigger_complete(self) -> None:
        """Flush the final invoke and close the current trigger file."""
        for runner_id in list(self._current_invokes):
            self._flush_current_invoke(runner_id)
        self._current_trigger_file = None

    def _flush_current_invoke(self, runner_id: str) -> None:
        current_invoke = self._current_invokes.pop(runner_id, None)
        if self._current_trigger_file and current_invoke is not None:
            self._write(self._current_trigger_file, current_invoke)
