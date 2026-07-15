"""Smoke test two conversational turns in a non-persistent session."""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
from dynamic_agent_client import DynamicAgentClient
from dynamic_agent_client.service_handler import ServiceHandler

load_dotenv()


SESSION_ID = "smoke-basic-chat"


async def main():
    client = None

    try:
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

        follow_up = await client.trigger(
            "What single word did you just say? Reply with only that word.",
            on_stream=on_stream,
        )
        print()
        assert "pong" in follow_up.lower(), "expected in-memory history to be available"

        print("ALL PASSED")
    finally:
        if client is not None:
            await client.close()

        await ServiceHandler.stop()


if __name__ == "__main__":
    asyncio.run(main())
