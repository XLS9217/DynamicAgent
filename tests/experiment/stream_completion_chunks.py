"""Stream one OpenAI invocation and record every raw completion chunk as JSONL."""

import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
load_dotenv(REPO_ROOT / ".env")

from dynamic_agent_service.external_service.openai_adapter import OpenAIAdapter
from dynamic_agent_service.external_service.openai_resource_accessor import OpenAIResourceAccessor
from dynamic_agent_service.external_service.pg_instance import PgInstance


OUTPUT_PATH = Path(os.getenv("CACHE_DIR") or REPO_ROOT / ".cache") / "experiment" / "stream_completion_chunks.jsonl"


async def main() -> None:
    await PgInstance.initialize()
    try:
        resource = await OpenAIResourceAccessor.get_active_resource()
        if resource is None:
            raise RuntimeError("No enabled OpenAI resource is configured")

        adapter = OpenAIAdapter(
            api_key=resource.api_key,
            base_url=resource.base_url,
            model=resource.model,
        )

        chunk_count = 0
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with OUTPUT_PATH.open("w", encoding="utf-8") as output:
            async for chunk in adapter.async_stream_response(
                messages=[{"role": "user", "content": "hello"}],
            ):
                chunk_count += 1
                record = {
                    "chunk_index": chunk_count,
                    "received_at": datetime.now(UTC).isoformat(),
                    "chunk": chunk.model_dump(mode="json"),
                }
                output.write(json.dumps(record, ensure_ascii=False) + "\n")

        print(f"Recorded {chunk_count} chunks")
        print(f"Output: {OUTPUT_PATH}")
    finally:
        await PgInstance.close()


if __name__ == "__main__":
    asyncio.run(main())
