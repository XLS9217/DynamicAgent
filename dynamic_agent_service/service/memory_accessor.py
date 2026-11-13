"""Script name: memory_accessor.py. Store session-scoped memory checkpoints."""
import json
from dynamic_agent_service.external_service.pg_instance import PgInstance
from dynamic_agent_service.external_service.redis_instance import RedisInstance


class MemoryAccessor:
    """Keep chat memory durable and task memory ephemeral."""

    @staticmethod
    async def save(session_id: str, session_type: str, checkpoint: dict, message) -> dict:
        """Atomically save the compacted user message and its checkpoint."""
        if session_type == "chat":
            async with PgInstance.get_pool().acquire() as conn:
                async with conn.transaction():
                    await conn.execute(
                        "INSERT INTO session_message(message_id, session_id, content) VALUES($1,$2,$3::jsonb)",
                        checkpoint["last_message_id"], session_id, message.model_dump_json())
                    await conn.execute("""
                        INSERT INTO session_memory_checkpoint(id,session_id,summary,compacted,last_message_id)
                        VALUES($1,$2,$3,$4,$5)
                    """, checkpoint["id"], session_id, checkpoint["summary"],
                        checkpoint["compacted"], checkpoint["last_message_id"])
            # Chat context reads PostgreSQL directly; invalidate the full-history cache.
            try:
                await RedisInstance.get_client().delete(f"session:{session_type}:{session_id}:messages")
            except Exception:
                import logging
                logging.getLogger(__name__).warning("Could not invalidate chat history cache after compaction")
            return checkpoint
        redis = RedisInstance.get_client()
        async with redis.pipeline(transaction=True) as pipe:
            pipe.rpush(f"session:{session_type}:{session_id}:messages", message.model_dump_json())
            pipe.hset(f"session:{session_type}:{session_id}:memory", checkpoint["last_message_id"], json.dumps(checkpoint))
            await pipe.execute()
        return checkpoint

    @staticmethod
    async def all(session_id: str, session_type: str) -> list[dict]:
        """Read checkpoints only within the current session."""
        if session_type == "chat":
            async with PgInstance.get_pool().acquire() as conn:
                rows = await conn.fetch("""
                    SELECT c.id,c.summary,c.compacted,c.last_message_id
                    FROM session_memory_checkpoint c JOIN session_message m
                      ON m.session_id=c.session_id AND m.message_id=c.last_message_id
                    WHERE c.session_id=$1 ORDER BY m.sequence_no
                """, session_id)
            return [{k:str(v) for k,v in dict(row).items()} for row in rows]
        values = await RedisInstance.get_client().hvals(f"session:{session_type}:{session_id}:memory")
        return [json.loads(value) for value in values]
