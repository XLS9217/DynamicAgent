"""
uv run -m examples.knowledge_retrieve
"""
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

from dynamic_agent_client import DynamicAgentClient


async def main():
    port = os.getenv("PORT", "7777")

    # Connect to service
    await DynamicAgentClient.connect(server_addr=f"http://localhost:{port}")

    bucket_name = "claude_mythos_blog"

    # Check if bucket exists
    print(f"Checking bucket: {bucket_name}...")
    result = await DynamicAgentClient.check_bucket(bucket_name)
    if not result["exists"]:
        print(f"Error: Bucket '{bucket_name}' does not exist!")
        print(f"Please run 'uv run -m examples.knowledge_inbound' first to create and populate the bucket.")
        return

    print(f"Bucket exists: {bucket_name}")

    # Create session with bucket
    client = await DynamicAgentClient.create(
        setting="You are a helpful assistant with knowledge about Claude Mythos Preview.",
        bucket_name=bucket_name
    )
    print(f"Session created: {client.session_id}")

    def on_stream(chunk: str):
        print(chunk, end="", flush=True)

    def on_rag(knowledge: list):
        print(f"[RAG retrieved {len(knowledge)} knowledge instances]")
        for i, instance in enumerate(knowledge, 1):
            print(f"  --- Knowledge {i} ---")
            for attr_name, attr_value in instance.items():
                print(f"    {attr_name}: {attr_value}")

    # Ask a question about the knowledge
    print("\nQuerying: What are the key cybersecurity capabilities of Claude Mythos Preview?\n")
    await client.trigger(
        "What are the key cybersecurity capabilities of Claude Mythos Preview?",
        on_stream=on_stream,
        on_rag=on_rag,
    )
    print("\n")

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())