import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from dynamic_agent_service.external_service.openai_resource_accessor import (
    OpenAIResourceAccessor,
)
from dynamic_agent_service.external_service.openai_resource_structs import (
    OpenAIResourceCreate,
)
from dynamic_agent_service.external_service.pg_instance import PgInstance
from dynamic_agent_service.init_storage import initialize_storage


def _pool_with_connection(connection):
    acquire = MagicMock()
    acquire.return_value.__aenter__ = AsyncMock(return_value=connection)
    acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.acquire = acquire
    return pool


class OpenAIResourceAccessorTest(unittest.IsolatedAsyncioTestCase):
    async def test_create_and_list_enabled_resources(self):
        row = {
            "resource_id": "resource-1",
            "model": "gpt-test",
            "api_key": "secret",
            "base_url": "https://example.test/v1",
            "enabled": True,
            "priority": 10,
        }
        connection = MagicMock()
        connection.fetchrow = AsyncMock(return_value=row)
        connection.fetch = AsyncMock(return_value=[row])
        pool = _pool_with_connection(connection)

        with patch.object(PgInstance, "get_pool", return_value=pool):
            created = await OpenAIResourceAccessor.create_resource(OpenAIResourceCreate(
                model="gpt-test",
                api_key="secret",
                base_url="https://example.test/v1",
                priority=10,
            ))
            resources = await OpenAIResourceAccessor.list_resources()
            active = await OpenAIResourceAccessor.get_active_resource()

        self.assertEqual(created.model, "gpt-test")
        self.assertEqual(resources, [created])
        self.assertEqual(active, created)
        self.assertIn("WHERE enabled = TRUE", connection.fetch.await_args.args[0])
        self.assertIn("ORDER BY priority DESC", connection.fetch.await_args.args[0])
        self.assertIn("LIMIT 1", connection.fetchrow.await_args.args[0])

    async def test_initialize_storage_creates_complete_schema_in_transaction(self):
        connection = MagicMock()
        connection.execute = AsyncMock()
        transaction = MagicMock()
        transaction.__aenter__ = AsyncMock(return_value=None)
        transaction.__aexit__ = AsyncMock(return_value=None)
        connection.transaction.return_value = transaction
        pool = _pool_with_connection(connection)

        with patch.object(PgInstance, "get_pool", return_value=pool):
            await initialize_storage()

        schema = "\n".join(call.args[0] for call in connection.execute.await_args_list)
        self.assertIn("CREATE TABLE IF NOT EXISTS bucket", schema)
        self.assertIn("CREATE TABLE IF NOT EXISTS session_message", schema)
        self.assertIn("CREATE TABLE IF NOT EXISTS openai_resource", schema)
        transaction.__aenter__.assert_awaited_once()
        transaction.__aexit__.assert_awaited_once()

    async def test_list_including_disabled_still_excludes_deleted_resources(self):
        connection = MagicMock()
        connection.fetch = AsyncMock(return_value=[])
        pool = _pool_with_connection(connection)

        with patch.object(PgInstance, "get_pool", return_value=pool):
            await OpenAIResourceAccessor.list_resources(enabled_only=False)

        query = connection.fetch.await_args.args[0]
        self.assertIn("WHERE deleted_at IS NULL", query)

    async def test_delete_is_idempotent_for_an_existing_resource(self):
        connection = MagicMock()
        connection.execute = AsyncMock(return_value="UPDATE 1")
        pool = _pool_with_connection(connection)

        with patch.object(PgInstance, "get_pool", return_value=pool):
            deleted = await OpenAIResourceAccessor.delete_resource("resource-1")

        self.assertTrue(deleted)
        query = connection.execute.await_args.args[0]
        self.assertIn("COALESCE(deleted_at, NOW())", query)
        self.assertNotIn("deleted_at IS NULL", query)


if __name__ == "__main__":
    unittest.main()
