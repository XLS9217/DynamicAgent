import os
import unittest
import uuid

from dotenv import load_dotenv

from dynamic_agent_client import DynamicAgentClient
from dynamic_agent_client.service_handler import ServiceHandler
from dynamic_agent_service.service.session_accessor import SessionAccessor
from tests.test_util.storage_check import (
    assert_session_redis_only,
    storage_connections,
    wait_for_session_deleted,
)


load_dotenv()


class SessionStorageCleanupIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_expired_session_is_removed_from_process_and_redis(self):
        session_id = f"integration-cleanup-{uuid.uuid4()}"
        expected = [{"role": "user", "content": "ephemeral test message"}]
        client = None

        async with storage_connections():
            try:
                port = os.getenv("PORT", "7777")
                await DynamicAgentClient.connect(f"http://localhost:{port}")
                client = await DynamicAgentClient.create(
                    setting="Integration-test session.",
                    reconnect_keep=1,
                    session_id=session_id,
                )

                await SessionAccessor.append_message(
                    session_id,
                    role="user",
                    content="ephemeral test message",
                    durable=False,
                )
                await assert_session_redis_only(session_id, expected)

                await client.close()
                client = None

                # Cleanup runs every 10 seconds, in addition to reconnect_keep.
                await wait_for_session_deleted(session_id, timeout=15)
            finally:
                if client is not None:
                    await client.close()
                await ServiceHandler.stop()
                # Remove leftovers if the assertion fails before service cleanup.
                await SessionAccessor.delete_session(session_id)


if __name__ == "__main__":
    unittest.main()
