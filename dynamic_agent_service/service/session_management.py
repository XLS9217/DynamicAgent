import logging
import uuid
from fastapi import WebSocket, WebSocketDisconnect

from dynamic_agent_service.agent.agent_general_interface import AgentGeneralInterface
from dynamic_agent_service.service.session_service_structs import AgentResponseChunk

logger = logging.getLogger(__name__)


class RealtimeSession:

    def __init__(self, setting: str):
        self.session_id = str(uuid.uuid4())
        self.setting = setting
        self.client: WebSocket | None = None
        self.agi: AgentGeneralInterface | None = None

    async def agent_setup(self):
        self.agi = await AgentGeneralInterface.create(
            language_engine=None,
            setting=self.setting,
        )
        logger.info("AGI initialized for session %s", self.session_id)

    def attach_websocket(self, client: WebSocket):
        self.client = client

    async def listen(self):
        try:
            while True:
                message = await self.client.receive_json()
                logger.info("received message %s", message)
                await self.handle_message(message)
        except WebSocketDisconnect:
            logger.info("WebSocketDisconnect")
        except Exception as e:
            logger.error("Error: %s", e)

    async def handle_message(self, message: dict):
        msg_type = message.get("type")

        if msg_type == "invoke":
            async def stream_callback(chunk: str, finished: bool = False):
                resp = AgentResponseChunk(type="agent_chunk", text=chunk, finished=finished)
                await self.client.send_json(resp.model_dump())

            full_text = await self.agi.trigger(message, stream_callback=stream_callback)
            await stream_callback("", finished=True)

        else:
            logger.warning("unknown message type: %s", msg_type)


class RealtimeSessionManager:
    _sessions: dict[str, RealtimeSession] = {}

    @classmethod
    def create(cls, setting: str) -> RealtimeSession:
        session = RealtimeSession(setting)
        cls._sessions[session.session_id] = session
        return session

    @classmethod
    def get(cls, session_id: str) -> RealtimeSession | None:
        return cls._sessions.get(session_id)

    @classmethod
    def remove(cls, session: RealtimeSession):
        cls._sessions.pop(session.session_id, None)