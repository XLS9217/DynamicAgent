"""Creation, lookup and expiration of active agent sessions."""
import asyncio
import time
import logging

from dynamic_agent_service.logging.log_interface import LogInterface
from dynamic_agent_service.service.service_structs import CreateSessionRequest
from dynamic_agent_service.service.session_accessor import SessionAccessor

from .agent_session_base import AgentSessionBase
from .chat_agent_session import ChatAgentSession
from .task_agent_session import TaskAgentSession


class SessionManager:
    _sessions: dict[str, AgentSessionBase] = {}
    _cleanup_task: asyncio.Task | None = None

    @classmethod
    async def create(cls, request: CreateSessionRequest) -> AgentSessionBase:
        existing = cls._sessions.get(request.session_id) if request.session_id else None
        if existing is not None and existing.session_type != request.session_type:
            raise ValueError("A session ID cannot change session_type")
        if request.session_type == "task":
            if request.session_id is not None:
                if existing is None or existing.is_expired():
                    raise ValueError("Task session expired or unavailable on this process")
                return existing
            session = TaskAgentSession(setting=request.setting, reconnect_keep=request.reconnect_keep)
        else:
            stored_meta = await SessionAccessor.load_meta(request.session_id) if request.session_id else None
            previous = stored_meta or existing
            compact_prompt = request.compact_prompt
            if "compact_prompt" not in request.model_fields_set and previous is not None:
                compact_prompt = previous.compact_prompt
            session = ChatAgentSession(
                setting=request.setting, session_id=request.session_id, reconnect_keep=request.reconnect_keep,
                soft_limit_count=request.soft_limit_count, hard_limit_count=request.hard_limit_count,
                compact_prompt=compact_prompt,
            )
            if stored_meta is not None:
                session.created_at = stored_meta.created_at
            await SessionAccessor.save_meta(session.meta())
        cls._sessions[session.session_id] = session
        cls._ensure_cleanup_task()
        return session

    @classmethod
    def get(cls, session_id: str) -> AgentSessionBase | None:
        return cls._sessions.get(session_id)

    @classmethod
    async def mark_disconnected(cls, session: AgentSessionBase):
        """Mark session as disconnected, starts reconnect_keep countdown."""
        session.disconnect_time = time.time()
        if isinstance(session, ChatAgentSession):
            await SessionAccessor.save_meta(session.meta())

    @classmethod
    async def cleanup_expired(cls):
        """Remove expired sessions from process memory and Redis."""
        expired = [sid for sid, session in cls._sessions.items() if session.is_expired()]
        for sid in expired:
            session = cls._sessions.pop(sid, None)
            if session is not None:
                try:
                    await session.stop()
                    await session.expire_cache()
                except Exception:
                    pass
                LogInterface.release_session(sid)

        for session in tuple(cls._sessions.values()):
            if isinstance(session, TaskAgentSession):
                try:
                    await session.refresh_images()
                except Exception:
                    logging.getLogger(__name__).exception("Failed to refresh image cache for %s", session.session_id)

    @classmethod
    def _ensure_cleanup_task(cls):
        """Start background cleanup task if not already running."""
        if cls._cleanup_task is None or cls._cleanup_task.done():
            cls._cleanup_task = asyncio.create_task(cls._cleanup_loop())

    @classmethod
    async def _cleanup_loop(cls):
        """Background task that runs cleanup_expired every 10 seconds."""
        while True:
            await asyncio.sleep(10)
            await cls.cleanup_expired()
