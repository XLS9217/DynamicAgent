"""
Convert files to text using vision-language model (VLM).

Converts file (path or bytes) into images, then extracts text and content descriptions
from each page in parallel using VLM. Returns merged text with page markers. Preserves
the original language of the content. Handles multi-page documents efficiently with
concurrent processing.
"""
import asyncio
from PIL import Image

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
    def __init__(self):
        super().__init__()
        self.images = []

    async def build(self, file_source: str | bytes, filetype: str):
        self.images = file_to_images(file_source, filetype)
        return self

    async def _extract_page(self, page_num: int) -> tuple[int, str]:
        text = await self.invoke_agent(
            [{"role": "system", "content": SYSTEM_PROMPT}],
            [self.images[page_num]]
        )
        self.append_log(f"Page {page_num + 1} extracted")
        return (page_num, text)

    async def execute(self) -> str:
        self.append_log(f"Extracting {len(self.images)} pages")
        tasks = [self._extract_page(i) for i in range(len(self.images))]
        results = await asyncio.gather(*tasks)
        results.sort(key=lambda x: x[0])
        merged = "\n\n".join([f"# Page {num + 1}\n{text}" for num, text in results])
        self.append_log(f"Extracted {len(merged)} characters")
        return merged
