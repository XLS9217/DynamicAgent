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
        """
        use .env to find cache folder, everything says in CACHE_FOLDER_PATH/session_log/session_id/file.log
        """
        self.session_id = session_id
        cache_folder = os.getenv("CACHE_DIR")
        self.log_dir = Path(cache_folder) / "session_log" / session_id
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.trigger_count = 0
        self.current_trigger_file = None
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

    def log(self, file: str, line: dict):
        """
        Fire-and-forget log. Returns immediately without waiting for write.
        """
        self._ensure_writer()
        self._write_queue.put_nowait((file, line))

    def trigger_new(self, tools: list, init_messages: list):
        """
        Start a new trigger log. Increment count, log tools and initial messages.
        Returns the trigger file name.
        """
        self.trigger_count += 1
        self.current_trigger_file = f"trigger_{self.trigger_count}"

        # Log tools
        for tool in tools:
            self.log(self.current_trigger_file, {"type": "tool", "tool": tool})

        # Log initial messages
        for msg in init_messages:
            self.log(self.current_trigger_file, msg)

        return self.current_trigger_file

    def trigger_log(self, line: dict):
        """
        Log a line to the current trigger file (fire-and-forget).
        """
        if self.current_trigger_file:
            self.log(self.current_trigger_file, line)
