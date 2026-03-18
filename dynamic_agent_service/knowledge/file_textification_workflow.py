"""
Extract text from files using VLM
"""
import asyncio
from PIL import Image

from dynamic_agent_service.agent.vision_engine import VisionEngine
from dynamic_agent_service.util.file_process import file_to_images

SYSTEM_PROMPT = """
Extract all text and content from the image. Preserve the original language of the content.

Output format:
## Text in Image
[exact text from the image, word for word]
## Content Description
[describe the image content]
"""


class FileTextificationWorkflow:
    def __init__(self, vision_engine: VisionEngine, file_source: str | bytes, filetype: str):
        """
        Args:
            vision_engine: VisionEngine instance
            file_source: File path (str) or raw bytes (bytes)
            filetype: File extension (e.g. "pdf", "png", "jpg")
        """
        self.vision_engine = vision_engine
        self.images = file_to_images(file_source, filetype)

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