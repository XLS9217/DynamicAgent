"""
Smoke test the basic chat flow using a deterministic custom session ID.

The script creates a session, sends one normal chat trigger, resumes the same
session to verify server-side message persistence, then deletes the test session.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
from dynamic_agent_client import DynamicAgentClient
from dynamic_agent_client.service_handler import ServiceHandler
from dynamic_agent_service.external_service.pg_instance import PgInstance
from dynamic_agent_service.external_service.redis_instance import RedisInstance
from dynamic_agent_service.service.session_accessor import SessionAccessor

load_dotenv()


SESSION_ID = "smoke-basic-chat"


async def main():
    await PgInstance.initialize()
    await RedisInstance.initialize()

    client = None
    resumed_client = None

    try:
        await SessionAccessor.delete_session(SESSION_ID)

        port = os.getenv("PORT", "7777")
        await DynamicAgentClient.connect(server_addr=f"http://localhost:{port}")

        client = await DynamicAgentClient.create(
            setting="You are a concise assistant.",
            session_id=SESSION_ID,
        )
        print(f"session_id: {client.session_id}")
        print(f"messages on create: {client.messages}")
        assert client.session_id == SESSION_ID
        assert client.messages == [], "fresh smoke session should start empty"

        def on_stream(chunk: str):
            print(chunk, end="", flush=True)

        print("\n--- trigger ---")
        response = await client.trigger("Say 'pong' and nothing else.", on_stream=on_stream)
        print()
        assert response, "expected a non-empty assistant response"

        await client.close()
        client = None

        resumed_client = await DynamicAgentClient.create(
            setting="You are a concise assistant.",
            session_id=SESSION_ID,
        )
        print(f"messages on resume: {resumed_client.messages}")
        assert len(resumed_client.messages) >= 2, "resume should load persisted user/assistant messages"
        assert resumed_client.messages[-2]["role"] == "user"
        assert resumed_client.messages[-2]["content"] == "Say 'pong' and nothing else."
        assert resumed_client.messages[-1]["role"] == "assistant"

        delete_result = await DynamicAgentClient.delete_session(SESSION_ID)
        print(f"delete session: {delete_result}")
        assert delete_result is True
        await resumed_client.close()
        resumed_client = None

        deleted_client = await DynamicAgentClient.create(
            setting="You are a concise assistant.",
            session_id=SESSION_ID,
        )
        print(f"messages after delete: {deleted_client.messages}")
        assert deleted_client.messages == [], "delete_session should clear persisted messages"
        await deleted_client.close()

        print("ALL PASSED")
    finally:
        if resumed_client is not None:
            await resumed_client.close()
        if client is not None:
            await client.close()

        await SessionAccessor.delete_session(SESSION_ID)
        await PgInstance.close()
        await RedisInstance.close()
        await ServiceHandler.stop()


if __name__ == "__main__":
    asyncio.run(main())
