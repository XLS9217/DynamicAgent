import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dynamic_agent_service.logging.cache_log_accessor import clear_system_log


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

if __name__ == "__main__":
    unittest.main()
