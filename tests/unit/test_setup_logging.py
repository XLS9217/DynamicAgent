import logging
import unittest

from dynamic_agent_service.util.setup_logging import SystemLogFilter, get_my_logger


class SetupLoggingTest(unittest.TestCase):
    def test_system_file_filter_excludes_agent_and_tool_categories(self):
        filter_ = SystemLogFilter()

        self.assertTrue(filter_.filter(logging.LogRecord(
            "src.system", logging.INFO, __file__, 1, "started", (), None,
        )))
        self.assertFalse(filter_.filter(logging.LogRecord(
            "src.agent", logging.INFO, __file__, 1, "tool call", (), None,
        )))
        self.assertFalse(filter_.filter(logging.LogRecord(
            "src.tool", logging.INFO, __file__, 1, "tool result", (), None,
        )))

    def test_logger_category_names(self):
        self.assertEqual(get_my_logger().name, "src.system")
        self.assertEqual(get_my_logger("agent").name, "src.agent")
        self.assertEqual(get_my_logger("tool").name, "src.tool")


if __name__ == "__main__":
    unittest.main()
