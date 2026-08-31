import tempfile
import unittest
import uuid
from pathlib import Path

from dotenv import load_dotenv

from dynamic_agent_service.external_service.pg_instance import PgInstance
from dynamic_agent_service.logging.cache_log_accessor import CacheLogAccessor
from dynamic_agent_service.logging.log_interface import LogInterface


load_dotenv()


class LogInterfaceIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.opened_pool = PgInstance._pool is None
        if self.opened_pool:
            await PgInstance.initialize()

        self.pool = PgInstance.get_pool()
        self.connection = await self.pool.acquire()
        self.transaction = self.connection.transaction()
        await self.transaction.start()

        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_cache_root = CacheLogAccessor.cache_log_root
        CacheLogAccessor.configure_root(self.temp_dir.name)
        CacheLogAccessor._trigger_locks.clear()
        LogInterface._contexts.clear()

    async def asyncTearDown(self):
        LogInterface._contexts.clear()
        CacheLogAccessor._trigger_locks.clear()
        CacheLogAccessor.cache_log_root = self.original_cache_root
        self.temp_dir.cleanup()

        await self.transaction.rollback()
        await self.pool.release(self.connection)
        if self.opened_pool:
            await PgInstance.close()

    async def test_database_trigger_and_resource_are_written_to_trigger_log(self):
        message_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())
        resource_id = str(uuid.uuid4())

        await self.connection.execute(
            """
            INSERT INTO session_message (message_id, session_id, role, content)
            VALUES ($1, $2, $3, $4)
            """,
            message_id,
            session_id,
            "user",
            "Integration logging request",
        )
        await self.connection.execute(
            """
            INSERT INTO openai_resource (
                resource_id, model, api_key, base_url, enabled, priority
            )
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            resource_id,
            "integration-test-model",
            "integration-test-key",
            "https://integration.example.test/v1",
            True,
            -999,
        )

        message_row = await self.connection.fetchrow(
            "SELECT message_id, session_id, role, content FROM session_message WHERE message_id = $1",
            message_id,
        )
        resource_row = await self.connection.fetchrow(
            "SELECT resource_id, model FROM openai_resource WHERE resource_id = $1",
            resource_id,
        )
        self.assertIsNotNone(message_row)
        self.assertIsNotNone(resource_row)

        LogInterface.configure_resource(session_id, str(resource_row["resource_id"]))
        LogInterface.start_trigger(session_id, str(message_row["message_id"]))
        invoke_id = await LogInterface.append_invoke_log(
            session_id=session_id,
            runner_id="integration-runner",
            parent_runner_id=None,
            messages=[{
                "role": message_row["role"],
                "content": message_row["content"],
            }],
            text="integration response",
            prompt_tokens=8,
            completion_tokens=3,
            usage_detail={
                "prompt_tokens": 8,
                "completion_tokens": 3,
                "total_tokens": 11,
            },
        )

        result = await CacheLogAccessor.read_log_file(
            f"trigger_log/{message_id}.jsonl"
        )
        self.assertEqual(result["format"], "jsonl")
        self.assertFalse(result["truncated"])
        self.assertEqual(len(result["entries"]), 1)

        record = result["entries"][0]
        self.assertEqual(record["invoke_id"], invoke_id)
        self.assertEqual(record["trigger_id"], str(message_row["message_id"]))
        self.assertEqual(record["resource_id"], str(resource_row["resource_id"]))
        self.assertEqual(record["runner_id"], "integration-runner")
        self.assertEqual(record["text"], "integration response")
        self.assertEqual(record["prompt_tokens"], 8)
        self.assertEqual(record["completion_tokens"], 3)
        self.assertEqual(record["usage_detail"]["total_tokens"], 11)
        self.assertIsNone(record["error"])

    async def test_large_log_file_is_read_in_full(self):
        log_dir = Path(self.temp_dir.name) / "trigger_log"
        log_dir.mkdir()
        payload = "x" * (2 * 1024 * 1024 + 1)
        (log_dir / "large.jsonl").write_text(
            '{"payload":"' + payload + '"}\n',
            encoding="utf-8",
        )

        result = await CacheLogAccessor.read_log_file("trigger_log/large.jsonl")

        self.assertFalse(result["truncated"])
        self.assertEqual(result["entries"][0]["payload"], payload)


if __name__ == "__main__":
    unittest.main()
