"""Script name: test_service_lifespan.py. Check startup using mocked persistence."""

import sys
import unittest
from unittest.mock import AsyncMock, patch

from dynamic_agent_service import __main__ as service


class ServiceLifespanTests(unittest.IsolatedAsyncioTestCase):
    """Exercise service startup/shutdown without model or database requests."""

    async def test_startup_only_initializes_postgres_and_redis(self):
        """Start without embedding/vector dependencies and close both stores."""
        with patch.object(service.PgInstance, 'initialize', AsyncMock()) as pg_start, \
             patch.object(service.PgInstance, 'close', AsyncMock()) as pg_close, \
             patch.object(service.RedisInstance, 'initialize', AsyncMock()) as redis_start, \
             patch.object(service.RedisInstance, 'close', AsyncMock()) as redis_close:
            async with service.lifespan(service.app):
                pg_start.assert_awaited_once()
                redis_start.assert_awaited_once()
                pg_close.assert_not_awaited()
                redis_close.assert_not_awaited()
                self.assertEqual(await service.health_check(), {'status': 'healthy'})
            pg_close.assert_awaited_once()
            redis_close.assert_awaited_once()
        self.assertNotIn('pymilvus', sys.modules)


if __name__ == '__main__':
    unittest.main()
