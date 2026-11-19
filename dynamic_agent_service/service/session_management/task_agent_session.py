"""Task sessions owned entirely by the current service process."""
import time
from uuid import uuid4

from dynamic_agent_service.external_service.redis_instance import RedisInstance
from dynamic_agent_service.service.media_storage import MediaStorage
from dynamic_agent_service.service.service_structs import MessageItem

from .agent_session_base import AgentSessionBase


class TaskAgentSession(AgentSessionBase):
    """Keep turns in RAM and cache image bytes for the live session."""

    session_type = "task"

    def __init__(self, setting: str, reconnect_keep: int = 30, session_id: str | None = None):
        super().__init__(setting, reconnect_keep, session_id)
        self._image_paths: set[str] = set()
        self._next_refresh = 0.0
        self._image_ttl = max(300, reconnect_keep + 60)
        self._messages: list[MessageItem] = []

    async def cache_images(self, uploads):
        """Create temporary image references for one upload."""
        images = await MediaStorage.cache_task_uploads(uploads, self.session_id, self._image_ttl)
        if images:
            self._image_paths.update(image.image_path for image in images)
        return images

    async def refresh_images(self):
        """Keep images available while the owning session is live."""
        if self._image_paths and time.monotonic() >= self._next_refresh:
            async with RedisInstance.get_client().pipeline(transaction=False) as pipe:
                for path in self._image_paths:
                    pipe.expire(path, self._image_ttl)
                await pipe.execute()
            self._next_refresh = time.monotonic() + 60

    async def append_message(self, role: str, content: str | MessageItem) -> str:
        """Keep a message with a stable ID in this task."""
        item = content if isinstance(content, MessageItem) else MessageItem.from_text(role, content)
        message_id = item.message_id or str(uuid4())
        self._messages.append(item.model_copy(update={"message_id": message_id}, deep=True))
        return message_id

    async def read_context(self) -> list[MessageItem]:
        """Return a snapshot of the task history."""
        return self._messages.copy()

    async def expire_cache(self) -> None:
        """Release task history and its image bytes."""
        self._messages.clear()
        if self._image_paths:
            await RedisInstance.get_client().delete(*self._image_paths)
            self._image_paths.clear()
