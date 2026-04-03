import json
import os
from pathlib import Path
from dotenv import load_dotenv
import aiofiles
from datetime import datetime
import asyncio

load_dotenv()


class SessionLogger:

    def __init__(self, session_id: str):
        self.session_id = session_id
        cache_folder = os.getenv("CACHE_DIR")
        self.log_dir = Path(cache_folder) / "session_log" / session_id
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._current_invoke_file = None
        self._write_queue = asyncio.Queue()
        self._writer_task = None

    async def _writer_loop(self):
        """Background task that processes write queue."""
        while True:
            file, line = await self._write_queue.get()
            try:
                log_file = self.log_dir / f"{file}.jsonl"
                line_with_timestamp = {"timestamp": datetime.utcnow().isoformat() + "Z", **line}
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

    # --- Invoke-level logging (invoke_YYYYMMDD_HHMMSS.jsonl) ---

    def invoke_new(self):
        """Start a new invoke log file. Named by current timestamp."""
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        self._current_invoke_file = f"invoke_{ts}"
        return self._current_invoke_file

    def invoke_log(self, line: dict):
        """Log a line to the current invoke file."""
        if self._current_invoke_file:
            self._write(self._current_invoke_file, line)