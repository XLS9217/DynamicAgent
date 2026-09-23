"""Script name: image_chat.py. Send a real image through the SDK and reuse its history."""

import asyncio
import os
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv

from dynamic_agent_client import DynamicAgentClient
from dynamic_agent_client.service_handler import ServiceHandler


async def main() -> None:
    """Verify live image upload, model vision, history reuse, and cleanup."""
    load_dotenv()
    image_path = Path(os.getenv("SMOKE_IMAGE_PATH", "experiment/test.png")).resolve()
    if not image_path.is_file():
        raise FileNotFoundError(
            f"Set SMOKE_IMAGE_PATH to an image file; default was {image_path}"
        )

    client = None
    await DynamicAgentClient.connect(f"http://localhost:{os.getenv('PORT', '7777')}")
    try:
        client = await DynamicAgentClient.create(
            setting="Describe supplied images accurately and answer in English.",
            session_id="smoke-image-" + uuid4().hex[:8],
        )
        first = await asyncio.wait_for(
            client.trigger(
                "What is in this image? Describe the subject, action, and visual effect.",
                images=[image_path],
            ),
            120,
        )
        print(f"image response: {first}", flush=True)
        description = first.lower()
        assert any(word in description for word in ("person", "man", "character")), first
        assert any(word in description for word in ("fire", "flame", "aura", "glow")), first

        follow_up = await asyncio.wait_for(
            client.trigger("What color was the prominent effect around the subject?"),
            120,
        )
        print(f"history response: {follow_up}", flush=True)
        assert any(word in follow_up.lower() for word in ("orange", "red", "fiery", "gold")), follow_up
        print("IMAGE INPUT + HISTORY PASSED", flush=True)
    finally:
        try:
            if client is not None:
                session_id = client.session_id
                await client.close()
                await DynamicAgentClient.delete_session(session_id)
        finally:
            await ServiceHandler.stop()


if __name__ == "__main__":
    asyncio.run(main())
