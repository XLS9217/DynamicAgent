# provide a redis instance
import os
from typing import Optional

import redis.asyncio as redis


class RedisInstance:
    _client: Optional[redis.Redis] = None

    @classmethod
    async def initialize(cls) -> None:
        """Initialize Redis client."""
        if cls._client is None:
            redis_url = os.getenv("REDIS_URL")
            cls._client = redis.from_url(redis_url, decode_responses=True)

    @classmethod
    def get_client(cls) -> redis.Redis:
        """Get Redis client instance."""
        if cls._client is None:
            raise RuntimeError("Redis not initialized. Call initialize() first.")
        return cls._client

    @classmethod
    async def close(cls) -> None:
        """Close Redis client."""
        if cls._client is not None:
            await cls._client.aclose()
            cls._client = None