import base64
import io
from PIL import Image
from openai import AsyncOpenAI

from dynamic_agent_service.util.setup_logging import get_my_logger

logger = get_my_logger()


class VisionEngine:

    def __init__(self, api_key: str, base_url: str, model: str):
        """
        Initialize the Vision Engine with API credentials

        Args:
            api_key: API key for the VLM service
            base_url: Base URL for the VLM API
            model: Model name to use
        """
        self.async_client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        self.model = model

    async def async_get_response(
            self,
            messages: list,
            images: list[Image.Image]
    ) -> str:
        """
        Generate an async blocking response from the VLM with images

        :param messages: List of message dicts in OpenAI format
        :param images: List of PIL Image objects to include
        :return: Complete response text
        """
        # Convert PIL Images to base64
        image_contents = []
        for img in images:
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=85)
            img_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
            image_contents.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}
            })

        # Add images to the last user message or create one
        if messages and messages[-1]["role"] == "user":
            if isinstance(messages[-1]["content"], str):
                messages[-1]["content"] = [
                    {"type": "text", "text": messages[-1]["content"]},
                    *image_contents
                ]
            elif isinstance(messages[-1]["content"], list):
                messages[-1]["content"].extend(image_contents)
        else:
            messages.append({"role": "user", "content": image_contents})

        response = await self.async_client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=False
        )

        return response.choices[0].message.content