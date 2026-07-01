import asyncio
import json
import re
import time
import uuid
from fastapi import WebSocket, WebSocketDisconnect

from dynamic_agent_service.agent.agent_general_interface import AgentGeneralInterface
from dynamic_agent_service.agent.agent_structs import AgentToolCall
from dynamic_agent_service.service.service_structs import AgentResponseChunk, CreateSessionRequest, RagCache
from dynamic_agent_service.util.setup_logging import get_my_logger
from dynamic_agent_service.service.session_logger import SessionLogger
from dynamic_agent_service.service.session_accessor import SessionAccessor
from dynamic_agent_service.service.monitor_events import MonitorEventHub, session_event_payload
from dynamic_agent_service.external_service.redis_instance import RedisInstance

logger = get_my_logger()

def _sanitize_json(raw: str) -> str:
    """Fix common LLM JSON quirks like leading zeros (e.g. 00.5 -> 0.5)."""
    return re.sub(r'(?<![0-9])0+(\d+\.)', r'\1', raw)


def _tool_arguments_to_object(raw: str | dict | None) -> dict:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        arguments = json.loads(_sanitize_json(raw or "{}"))
    except (json.JSONDecodeError, TypeError, ValueError):
        logger.warning("Failed to parse tool arguments as JSON: %s", raw)
        return {}
    if not isinstance(arguments, dict):
        return {}
    return arguments


class RealtimeSession:
    def __init__(self, setting: str, reconnect_keep: int = 30, session_id: str = None):
        self.session_id = session_id or str(uuid.uuid4())
        self.setting = setting
        self.reconnect_keep = reconnect_keep
        self.disconnect_time: float | None = None
        self.client: WebSocket | None = None
        self.agi: AgentGeneralInterface | None = None
        self.session_logger = SessionLogger(self.session_id)
        self.active_trigger_task: asyncio.Task | None = None

    @property
    def state(self) -> str:
        if self.agi is None:
            return "idle"
        if self.active_trigger_task is not None and not self.active_trigger_task.done() and self.agi.state == "idle":
            return "running"
        return self.agi.state

    # ===== Redis-backed session state (keys owned here, not in RedisInstance) =====

    def _rag_key(self) -> str:
        return f"session:{self.session_id}:rag"

    async def append_message(self, role: str, content: str) -> None:
        await SessionAccessor.append_message(self.session_id, role, content)

    async def load_messages(self) -> list[dict]:
        messages = await SessionAccessor.load_messages(self.session_id)
        return [m.model_dump() for m in messages]

    async def set_rag(self, rag: RagCache) -> None:
        client = RedisInstance.get_client()
        await client.set(self._rag_key(), rag.model_dump_json())

    async def get_rag(self) -> RagCache | None:
        client = RedisInstance.get_client()
        raw = await client.get(self._rag_key())
        return RagCache.model_validate_json(raw) if raw else None

    async def agent_setup(self):
        self.agi = await AgentGeneralInterface.create(
            language_engine=None,
            setting=self.setting,
            send_tool_calls=self._send_tool_calls,
            session_logger=self.session_logger,
        )
        logger.info("AGI initialized for session %s", self.session_id)
        self.session_logger.log_system("agent_setup", {
            "session_id": self.session_id,
            "setting": self.setting,
            "reconnect_keep": self.reconnect_keep,
        })

    async def attach_websocket(self, client: WebSocket):
        # Close old WebSocket if exists
        if self.client is not None:
            await self.client.close()
            self.session_logger.log_system("websocket_replaced")

        self.client = client
        self.disconnect_time = None
        self.session_logger.log_system("websocket_connected")
        MonitorEventHub.publish_nowait("session_join", session_event_payload(self))

        async def stream_callback(chunk: AgentResponseChunk):
            await self.client.send_json(chunk.model_dump())

        self.agi._stream_callback = stream_callback
        if self.agi.state == "gathering_tool_result" and self.agi.pending_tool_calls:
            await self._send_tool_calls(list(self.agi.pending_tool_calls.values()))

    def register_operator(self, operator_data: dict):
        """Forward serialized operator data to AGI for registration."""
        self.agi.register_operator(operator_data)
        self.session_logger.log_system("operator_registered", {"operator_name": operator_data.get("name")})

    def is_expired(self) -> bool:
        """Check if session has been disconnected longer than reconnect_keep seconds."""
        return self.disconnect_time is not None and time.time() - self.disconnect_time > self.reconnect_keep

    async def listen(self):
        """Keep WebSocket alive for receiving messages (if needed in future)."""
        try:
            while True:
                message = await self.client.receive_json()
                logger.info("received message %s", message)
        except WebSocketDisconnect:
            logger.info("WebSocketDisconnect")
        except Exception as e:
            logger.error("Error: %s", e)

    async def trigger_agent(self, text: str, bucket_name: str = None):
        """Trigger agent with text input. Response streams via WebSocket."""
        if self.client is None:
            raise RuntimeError("WebSocket not connected")
        if self.agi.state != "idle":
            raise RuntimeError(f"Agent is {self.agi.state}")

        try:
            message = {"type": "invoke", "text": text}

            # Fetch history before this turn's message
            history = await self.load_messages()

            # Trigger agent with history; AGI owns the in-progress invoke state.
            await self.agi.trigger(
                message,
                history=history,
                bucket_name=bucket_name,
            )
        except Exception as e:
            logger.error("Error processing trigger: %s", e)
            error_chunk = AgentResponseChunk(type="agent_chunk", text="Error Occurred", finished=True, invoked=True)
            if self.client is not None:
                await self.client.send_json(error_chunk.model_dump())
        finally:
            self.active_trigger_task = None

    async def receive_tool_result(self, tool_call_id: str, ok: bool, result: object) -> None:
        await self.agi.append_tool_result(tool_call_id=tool_call_id, ok=ok, result=result)

    async def _send_tool_calls(self, tool_calls: list[AgentToolCall]) -> None:
        if self.client is None:
            return
        for tool_call in tool_calls:
            await self.client.send_json({
                "type": "tool_call",
                "session_id": self.session_id,
                "tool_call_id": tool_call.id,
                "name": tool_call.name,
                "arguments": _tool_arguments_to_object(tool_call.arguments),
            })


class RealtimeSessionManager:
    _sessions: dict[str, RealtimeSession] = {}
    _cleanup_task: asyncio.Task | None = None

    @classmethod
    async def create(cls, request: CreateSessionRequest) -> RealtimeSession:
        session = RealtimeSession(
            setting=request.setting,
            reconnect_keep=request.reconnect_keep,
            session_id=request.session_id,
        )
        cls._sessions[session.session_id] = session
        cls._ensure_cleanup_task()
        MonitorEventHub.publish_nowait("session_created", session_event_payload(session))
        return session

    @classmethod
    def get(cls, session_id: str) -> RealtimeSession | None:
        return cls._sessions.get(session_id)

    @classmethod
    def mark_disconnected(cls, session: RealtimeSession):
        """Mark session as disconnected, starts reconnect_keep countdown."""
        session.disconnect_time = time.time()
        session.session_logger.log_system("websocket_disconnected")
        logger.info("Session %s marked disconnected, will expire in %s seconds", session.session_id, session.reconnect_keep)
        MonitorEventHub.publish_nowait("session_leave", session_event_payload(session))

    @classmethod
    def cleanup_expired(cls):
        """Remove sessions that have been disconnected longer than reconnect_keep."""
        expired = [sid for sid, session in cls._sessions.items() if session.is_expired()]
        for sid in expired:
            session = cls._sessions.pop(sid, None)
            logger.info("Session %s expired and removed", sid)
            if session is not None:
                MonitorEventHub.publish_nowait("session_expired", session_event_payload(session))

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
            cls.cleanup_expired()
