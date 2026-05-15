"""
uv run -m examples.knowledge_inbound
"""
import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from dynamic_agent_client import DynamicAgentClient


async def main():
    port = os.getenv("PORT", "7777")

    # Read the Claude mythos blog text
    text_path = Path(__file__).parent / "claude_mythos.txt"
    with open(text_path, "r", encoding="utf-8") as f:
        knowledge_text = f.read()

    print(f"Read {len(knowledge_text)} characters from {text_path.name}")

    # Connect to service
    await DynamicAgentClient.connect(server_addr=f"http://localhost:{port}")

    bucket_name = "claude_mythos_blog"

    # Check if bucket exists, delete if it does
    print(f"\nChecking bucket: {bucket_name}...")
    result = await DynamicAgentClient.check_bucket(bucket_name)
    if result["exists"]:
        print(f"Bucket exists, deleting...")
        await DynamicAgentClient.delete_bucket(bucket_name)
        print(f"Bucket deleted: {bucket_name}")

    # Create bucket
    print(f"\nCreating bucket: {bucket_name}...")
    await DynamicAgentClient.create_bucket(
        name=bucket_name,
        description="Test Knowledge about Claude Mythos Preview's cybersecurity capabilities"
    )
    print(f"Bucket created: {bucket_name}")

    # Inbound the knowledge
    instruction_query = "Find all products and exploits mentioned in the text"

    print(f"\nInbounding knowledge to bucket: {bucket_name}...")
    result = await DynamicAgentClient.inbound(
        instruction_query=instruction_query,
        knowledge_text=knowledge_text,
        bucket_name=bucket_name
    )
    print(f"Inbound completed: {result['status']}")
    print(f"Message: {result['message']}")


if __name__ == "__main__":
    asyncio.run(main())