import logging
import uuid
import requests
from fastapi import WebSocket, WebSocketDisconnect

from dynamic_agent_service.agent.agent_general_interface import AgentGeneralInterface
from dynamic_agent_service.agent.agent_structs import AgentToolCall
from dynamic_agent_service.service.service_structs import AgentResponseChunk
from dynamic_agent_service.util.setup_logging import get_my_logger

logger = get_my_logger()


class RealtimeSession:

    def __init__(self, setting: str, webhook_url: str):
        self.session_id = str(uuid.uuid4())
        self.setting = setting
        self.webhook_url = webhook_url
        self.client: WebSocket | None = None
        self.agi: AgentGeneralInterface | None = None

    async def agent_setup(self):

        async def tool_execute(tool_call: AgentToolCall) -> str:
            """POST tool_call to client webhook and return result."""
            payload = tool_call.model_dump()
            payload["session_id"] = self.session_id
            resp = requests.post(
                self.webhook_url,
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            return resp.text

        self.agi = await AgentGeneralInterface.create(
            language_engine=None,
            setting=self.setting,
            tool_execute=tool_execute,
        )
        logger.info("AGI initialized for session %s", self.session_id)

    def attach_websocket(self, client: WebSocket):
        self.client = client

    def register_operator(self, operator_data: dict):
        """Forward the serialized operator data to AGI for registration."""
        self.agi.register_operator(operator_data)

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

            async def stream_callback(chunk: str):
                resp = AgentResponseChunk(type="agent_chunk", text=chunk, finished=False)
                await self.client.send_json(resp.model_dump())

            full_response = await self.agi.trigger(message, stream_callback=stream_callback)

            final_chunk = AgentResponseChunk(type="agent_chunk", text="", finished=True)
            await self.client.send_json(final_chunk.model_dump())

        else:
            logger.warning("unknown message type: %s", msg_type)


class RealtimeSessionManager:
    _sessions: dict[str, RealtimeSession] = {}

    @classmethod
    def create(cls, setting: str, webhook_url: str) -> RealtimeSession:
        session = RealtimeSession(setting, webhook_url)
        cls._sessions[session.session_id] = session
        return session

    @classmethod
    def get(cls, session_id: str) -> RealtimeSession | None:
        return cls._sessions.get(session_id)

    @classmethod
    def remove(cls, session: RealtimeSession):
        cls._sessions.pop(session.session_id, None)