"""
Extract text from images using VLM in parallel
"""
import asyncio
from PIL import Image

from dynamic_agent_service.agent.vision_engine import VisionEngine

SYSTEM_PROMPT = """
Extract all text and content from the image. Preserve the original language of the content.

Output format:
## Text in Image
[exact text from the image, word for word]
## Content Description
[describe the image content]
"""


class KnowledgeExtractionWorkflow:
    def __init__(self, vision_engine: VisionEngine, images: list[Image.Image]):
        self.vision_engine = vision_engine
        self.images = images

    async def _extract_page(self, page_num: int) -> tuple[int, str]:
        text = await self.vision_engine.async_get_response(
            [{"role": "system", "content": SYSTEM_PROMPT}],
            [self.images[page_num]]
        )
        return (page_num, text)

    async def execute(self) -> str:
        tasks = [self._extract_page(i) for i in range(len(self.images))]
        results = await asyncio.gather(*tasks)
        results.sort(key=lambda x: x[0])
        return "\n\n".join([f"# Page {num + 1}\n{text}" for num, text in results])