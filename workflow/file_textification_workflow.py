"""
Extract text from files using VLM
"""
import asyncio
from PIL import Image

from dynamic_agent_service.agent.vision_engine import VisionEngine
from dynamic_agent_service.util.file_process import file_to_images
from workflow.workflow_base import WorkflowBase

SYSTEM_PROMPT = """
Extract all text and content from the image. Preserve the original language of the content.

Output format:
## Text in Image
[exact text from the image, word for word]
## Content Description
[describe the image content]
"""


class FileTextificationWorkflow(WorkflowBase):
    def __init__(self, vision_engine: VisionEngine, file_source: str | bytes, filetype: str):
        super().__init__()
        self.vision_engine = vision_engine
        self.images = file_to_images(file_source, filetype)

    async def _extract_page(self, page_num: int) -> tuple[int, str]:
        text = await self.vision_engine.async_get_response(
            [{"role": "system", "content": SYSTEM_PROMPT}],
            [self.images[page_num]]
        )
        self._append_log(f"Page {page_num + 1} extracted")
        return (page_num, text)

    async def execute(self) -> str:
        self._append_log(f"Extracting {len(self.images)} pages")
        tasks = [self._extract_page(i) for i in range(len(self.images))]
        results = await asyncio.gather(*tasks)
        results.sort(key=lambda x: x[0])
        merged = "\n\n".join([f"# Page {num + 1}\n{text}" for num, text in results])
        self._append_log(f"Extracted {len(merged)} characters")
        return merged
