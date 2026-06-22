"""
uv run -m examples.hello
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
        setting="You are a friendly assistant.",
    )
    print(f"Session created: {client.session_id}")

    def on_stream(chunk: str):
        print(chunk, end="", flush=True)

    await client.trigger("Say hello in one short sentence.", on_stream=on_stream)
    print()

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())