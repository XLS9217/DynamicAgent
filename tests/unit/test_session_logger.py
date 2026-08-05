import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dynamic_agent_service.service.session_logger import SessionLogger


class SessionLoggerTest(unittest.IsolatedAsyncioTestCase):
    async def test_one_trigger_file_contains_one_line_per_invoke(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CACHE_DIR": temp_dir},
        ):
            logger = SessionLogger("session-1")
            trigger_file = logger.trigger_new()
            logger.invoke_new()
            logger.invoke_log({"type": "messages", "messages": [{"role": "user", "content": "hi"}]})
            logger.invoke_new()
            logger.invoke_log({"type": "llm_response", "full_text": "hello"})
            logger.trigger_complete()
            await logger._write_queue.join()

            path = Path(temp_dir) / "session_log" / "session-1" / f"{trigger_file}.jsonl"
            lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

            self.assertEqual([line["invoke"] for line in lines], [1, 2])
            self.assertEqual(lines[0]["events"][0]["type"], "messages")
            self.assertEqual(lines[1]["events"][0]["type"], "llm_response")

            logger._writer_task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await logger._writer_task


if __name__ == "__main__":
    unittest.main()
