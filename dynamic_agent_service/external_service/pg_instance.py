# provide a postgresql instance
import os
from typing import Optional
from asyncpg import Pool, create_pool


class PgInstance:
    _pool: Optional[Pool] = None

    @classmethod
    async def initialize(cls) -> None:
        """Initialize PostgreSQL connection pool"""
        if cls._pool is None:
            pg_dsn = os.getenv("POSTGRES_DSN")

            cls._pool = await create_pool(
                dsn=pg_dsn,
                min_size=10,
                max_size=20
            )

    @classmethod
    def get_pool(cls) -> Pool:
        """Get PostgreSQL connection pool instance"""
        if cls._pool is None:
            raise RuntimeError("PostgreSQL pool not initialized. Call initialize() first.")
        return cls._pool

    @classmethod
    async def close(cls) -> None:
        """Close PostgreSQL connection pool"""
        if cls._pool is not None:
            await cls._pool.close()
            cls._pool = None