import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dynamic_agent_service.util.log_accessor import clear_session_logs, clear_system_log


class LogAccessorTest(unittest.IsolatedAsyncioTestCase):
    async def test_clear_system_log_truncates_only_system_file(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"CACHE_DIR": temp_dir}):
            root = Path(temp_dir)
            system_log = root / "system.log"
            other_log = root / "other.log"
            system_log.write_text("system data", encoding="utf-8")
            other_log.write_text("keep", encoding="utf-8")

            self.assertTrue(await clear_system_log())
            self.assertEqual(system_log.read_text(encoding="utf-8"), "")
            self.assertEqual(other_log.read_text(encoding="utf-8"), "keep")

    async def test_clear_session_logs_removes_only_selected_session_files(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"CACHE_DIR": temp_dir}):
            selected = Path(temp_dir) / "session_log" / "selected"
            other = Path(temp_dir) / "session_log" / "other"
            selected.mkdir(parents=True)
            other.mkdir(parents=True)
            (selected / "trigger.jsonl").write_text("{}", encoding="utf-8")
            (selected / "notes.txt").write_text("keep", encoding="utf-8")
            (other / "trigger.jsonl").write_text("{}", encoding="utf-8")

            self.assertEqual(await clear_session_logs("selected"), 1)
            self.assertFalse((selected / "trigger.jsonl").exists())
            self.assertTrue((selected / "notes.txt").exists())
            self.assertTrue((other / "trigger.jsonl").exists())

    async def test_clear_session_logs_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"CACHE_DIR": temp_dir}):
            self.assertEqual(await clear_session_logs("../"), 0)


if __name__ == "__main__":
    unittest.main()
