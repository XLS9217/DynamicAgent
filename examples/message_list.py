"""
uv run -m examples.message_list
"""
import asyncio
import os
from dotenv import load_dotenv

from dynamic_agent_client import DynamicAgentClient

load_dotenv()


async def main():
    port = os.getenv("PORT", "7777")

    await DynamicAgentClient.connect(server_addr=f"http://localhost:{port}")

    client = await DynamicAgentClient.create(
        setting="You are a knowledgeable hardware advisor.",
    )
    print(f"Session created: {client.session_id}")
    print(f"Initial messages returned on create: {client.messages}")

    def on_stream(chunk: str):
        print(chunk, end="", flush=True)

    response = await client.trigger(
        "In one sentence, what should I look for when buying an SSD?",
        on_stream=on_stream,
    )
    print()

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())