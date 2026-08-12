import asyncio
import json
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from dynamic_agent_service.external_service.openai_resource_structs import OpenAIResource
from dynamic_agent_service.logging.cache_log_accessor import CacheLogAccessor
from dynamic_agent_service.logging.log_interface import LogInterface


class LogInterfaceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_cache_root = CacheLogAccessor.cache_log_root
        CacheLogAccessor.configure_root(self.temp_dir.name)
        CacheLogAccessor._trigger_locks.clear()
        LogInterface._contexts.clear()

        self.session_message = {
            "message_id": str(uuid.uuid4()),
            "session_id": str(uuid.uuid4()),
            "role": "user",
            "content": "Find the current inventory.",
        }
        self.resource = OpenAIResource(
            resource_id=str(uuid.uuid4()),
            model="test-model",
            api_key="test-key",
            base_url="https://example.test/v1",
            enabled=True,
            priority=1,
        )
        LogInterface.configure_resource(
            self.session_message["session_id"],
            self.resource.resource_id,
        )
        LogInterface.start_trigger(
            self.session_message["session_id"],
            self.session_message["message_id"],
        )

    async def asyncTearDown(self):
        LogInterface._contexts.clear()
        CacheLogAccessor._trigger_locks.clear()
        CacheLogAccessor.cache_log_root = self.original_cache_root
        self.temp_dir.cleanup()

    def trigger_log_path(self) -> Path:
        return (
            Path(self.temp_dir.name)
            / "trigger_log"
            / f"{self.session_message['message_id']}.jsonl"
        )

    async def test_append_invoke_log_writes_canonical_flat_structure(self):
        invoke_id = await LogInterface.append_invoke_log(
            session_id=self.session_message["session_id"],
            runner_id="runner-main",
            parent_runner_id=None,
            messages=[{
                "role": self.session_message["role"],
                "content": self.session_message["content"],
            }],
            text="partial response",
            tool_use={
                "items": [{
                    "id": "call-1",
                    "name": "Inventory_lookup",
                    "arguments": "{\"sku\":\"A-1\"}",
                }],
            },
            prompt_tokens=12,
            completion_tokens=5,
            usage_detail={
                "prompt_tokens": 12,
                "completion_tokens": 5,
                "total_tokens": 17,
            },
        )

        lines = self.trigger_log_path().read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        record = json.loads(lines[0])
        self.assertEqual(set(record), {
            "invoke_id",
            "trigger_id",
            "runner_id",
            "parent_runner_id",
            "text",
            "tool_id",
            "tool_use",
            "tool_result",
            "resource_id",
            "prompt_tokens",
            "completion_tokens",
            "usage_detail",
            "error",
        })
        self.assertEqual(record["invoke_id"], invoke_id)
        self.assertEqual(record["trigger_id"], self.session_message["message_id"])
        self.assertEqual(record["resource_id"], self.resource.resource_id)
        self.assertEqual(record["text"], "partial response")
        self.assertEqual(record["tool_id"], "call-1")
        self.assertEqual(record["tool_use"]["items"][0]["id"], "call-1")
        self.assertEqual(record["prompt_tokens"], 12)
        self.assertEqual(record["completion_tokens"], 5)
        self.assertEqual(record["usage_detail"]["total_tokens"], 17)
        self.assertIsNone(record["tool_result"])
        self.assertIsNone(record["error"])

    async def test_concurrent_appends_are_complete_unique_json_lines(self):
        append_count = 100
        started_at = time.perf_counter()
        invoke_ids = await asyncio.gather(*[
            LogInterface.append_invoke_log(
                session_id=self.session_message["session_id"],
                runner_id=f"runner-{index % 4}",
                parent_runner_id=None,
                messages=[{
                    "role": "user",
                    "content": f"request-{index}",
                }],
                text=f"response-{index}",
                prompt_tokens=index,
                completion_tokens=1,
                usage_detail={"total_tokens": index + 1},
            )
            for index in range(append_count)
        ])
        elapsed_seconds = time.perf_counter() - started_at

        records = [
            json.loads(line)
            for line in self.trigger_log_path().read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(len(records), append_count)
        self.assertEqual(len(set(invoke_ids)), append_count)
        self.assertEqual({record["invoke_id"] for record in records}, set(invoke_ids))
        self.assertTrue(all(record["trigger_id"] == self.session_message["message_id"] for record in records))
        self.assertLess(elapsed_seconds, 5.0)
        print(f"LogInterface appended {append_count} records in {elapsed_seconds:.4f}s")

    async def test_append_without_trigger_uses_invoke_id_filename(self):
        session_id = str(uuid.uuid4())
        LogInterface.configure_resource(session_id, self.resource.resource_id)

        invoke_id = await LogInterface.append_invoke_log(
            session_id=session_id,
            runner_id="standalone-runner",
            parent_runner_id=None,
            messages=[],
            text="standalone response",
            prompt_tokens=2,
            completion_tokens=3,
            usage_detail={"total_tokens": 5},
        )

        path = Path(self.temp_dir.name) / "trigger_log" / f"{invoke_id}.jsonl"
        record = json.loads(path.read_text(encoding="utf-8"))
        self.assertIsNone(record["trigger_id"])
        self.assertEqual(record["invoke_id"], invoke_id)

    async def test_trigger_does_not_need_to_exist_in_database(self):
        arbitrary_trigger_id = str(uuid.uuid4())
        LogInterface.start_trigger(
            self.session_message["session_id"],
            arbitrary_trigger_id,
        )

        await LogInterface.append_invoke_log(
            session_id=self.session_message["session_id"],
            runner_id="runner-main",
            parent_runner_id=None,
            messages=[],
            text="not database backed",
        )

        path = Path(self.temp_dir.name) / "trigger_log" / f"{arbitrary_trigger_id}.jsonl"
        self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()
