import asyncio
import time
import uuid
import httpx
from fastapi import WebSocket, WebSocketDisconnect

from dynamic_agent_service.agent.agent_general_interface import AgentGeneralInterface
from dynamic_agent_service.agent.agent_structs import AgentToolCall
from dynamic_agent_service.service.service_structs import AgentResponseChunk, CreateSessionRequest
from dynamic_agent_service.util.setup_logging import get_my_logger
from dynamic_agent_service.service.session_logger import SessionLogger

logger = get_my_logger()


class RealtimeSession:

    _http: httpx.AsyncClient = None

    @classmethod
    def _get_http(cls) -> httpx.AsyncClient:
        if cls._http is None:
            cls._http = httpx.AsyncClient(mounts={"http://": None})
        return cls._http

    def __init__(self, setting: str, webhook_url: str, reconnect_keep: int = 30, messages: list = None, compact_limit: int = None, compact_target: int = None, bucket_name: str = None):
        self.session_id = str(uuid.uuid4())
        self.setting = setting
        self.messages = messages or []
        self.compact_limit = compact_limit
        self.compact_target = compact_target
        self.webhook_url = webhook_url
        self.reconnect_keep = reconnect_keep
        self.bucket_name = bucket_name
        self.disconnect_time: float | None = None
        self.client: WebSocket | None = None
        self.agi: AgentGeneralInterface | None = None
        self.session_logger = SessionLogger(self.session_id)

    async def agent_setup(self):

        async def tool_execute(tool_call: AgentToolCall) -> str:
            """POST tool_call to client webhook and return result."""
            payload = tool_call.model_dump()
            payload["session_id"] = self.session_id
            resp = await self._get_http().post(
                self.webhook_url,
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            return resp.text

        self.agi = await AgentGeneralInterface.create(
            language_engine=None,
            setting=self.setting,
            messages=self.messages,
            compact_limit=self.compact_limit,
            compact_target=self.compact_target,
            tool_execute=tool_execute,
            session_logger=self.session_logger,
            bucket_name=self.bucket_name,
        )
        logger.info("AGI initialized for session %s", self.session_id)
        self.session_logger.log_system("agent_setup", {
            "session_id": self.session_id,
            "setting": self.setting,
            "compact_limit": self.compact_limit,
            "compact_target": self.compact_target,
            "webhook_url": self.webhook_url,
            "reconnect_keep": self.reconnect_keep,
            "bucket_name": self.bucket_name,
        })

    def attach_websocket(self, client: WebSocket):
        self.client = client
        self.disconnect_time = None
        self.session_logger.log_system("websocket_connected")

        async def stream_callback(chunk: AgentResponseChunk):
            await self.client.send_json(chunk.model_dump())

        self.agi._stream_callback = stream_callback

    def register_operator(self, operator_data: dict):
        """Forward the serialized operator data to AGI for registration."""
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

    async def trigger_agent(self, text: str):
        """Trigger agent with text input. Response streams via WebSocket."""
        if self.client is None:
            raise RuntimeError("WebSocket not connected")

        # Start processing in background, return immediately
        asyncio.create_task(self._process_trigger(text))

    async def _process_trigger(self, text: str):
        """Background task to process trigger and stream response."""
        try:
            message = {"type": "invoke", "text": text}
            await self.agi.trigger(message)

            # Send final chunk
            final_chunk = AgentResponseChunk(type="agent_chunk", text="", finished=True, invoked=True)
            await self.client.send_json(final_chunk.model_dump())
        except Exception as e:
            logger.error("Error processing trigger: %s", e)
            error_chunk = AgentResponseChunk(type="agent_chunk", text="Error Occurred", finished=True, invoked=True)
            await self.client.send_json(error_chunk.model_dump())


class RealtimeSessionManager:
    _sessions: dict[str, RealtimeSession] = {}
    _cleanup_task: asyncio.Task | None = None

    @classmethod
    def create(cls, request: CreateSessionRequest, webhook_url: str) -> RealtimeSession:
        session = RealtimeSession(
            setting=request.setting,
            webhook_url=webhook_url,
            reconnect_keep=request.reconnect_keep,
            messages=request.messages,
            compact_limit=request.compact_limit,
            compact_target=request.compact_target,
            bucket_name=request.bucket_name,
        )
        cls._sessions[session.session_id] = session
        cls._ensure_cleanup_task()
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

    @classmethod
    def cleanup_expired(cls):
        """Remove sessions that have been disconnected longer than reconnect_keep."""
        expired = [sid for sid, session in cls._sessions.items() if session.is_expired()]
        for sid in expired:
            cls._sessions.pop(sid, None)
            logger.info("Session %s expired and removed", sid)

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