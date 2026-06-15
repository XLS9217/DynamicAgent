"""
uv run -m examples.knowledge_retrieve
"""
import asyncio
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

from dynamic_agent_client import DynamicAgentClient


async def main():
    port = os.getenv("PORT", "7777")
    server_addr = f"http://localhost:{port}"

    # Connect to service
    await DynamicAgentClient.connect(server_addr=server_addr)

    bucket_name = "claude_mythos_blog"

    # Check if bucket exists
    print(f"Checking bucket: {bucket_name}...")
    result = await DynamicAgentClient.check_bucket(bucket_name)
    if not result["exists"]:
        print(f"Error: Bucket '{bucket_name}' does not exist!")
        print(f"Please run 'uv run -m examples.knowledge_inbound' first to create and populate the bucket.")
        return

    print(f"Bucket exists: {bucket_name}")

    # Create session (bucket is attached per trigger, not at creation)
    client = await DynamicAgentClient.create(
        setting="You are a helpful assistant with knowledge about Claude Mythos Preview.",
    )
    print(f"Session created: {client.session_id}")

    def on_stream(chunk: str):
        print(chunk, end="", flush=True)

    # Ask a question about the knowledge, attaching the bucket for RAG this turn
    print("\nQuerying: What are the key cybersecurity capabilities of Claude Mythos Preview?\n")
    await client.trigger(
        "What are the key cybersecurity capabilities of Claude Mythos Preview?",
        on_stream=on_stream,
        bucket_name=bucket_name,
    )
    print("\n")

    # The RAG knowledge used for this answer is NOT pushed to the client.
    # It is cached server-side and can be fetched by session_id from the
    # monitor endpoint: GET /session/{session_id}/rag
    async with httpx.AsyncClient(mounts={"http://": None}) as http:
        resp = await http.get(f"{server_addr}/session/{client.session_id}/rag")
        resp.raise_for_status()
        rag = resp.json()["rag"]

    if rag:
        print(f"RAG used (query: {rag['query']}) — {len(rag['knowledge'])} instance(s):")
        for i, instance in enumerate(rag["knowledge"], 1):
            print(f"  --- Knowledge {i} ---")
            for attr_name, attr_value in instance.items():
                print(f"    {attr_name}: {attr_value}")

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())