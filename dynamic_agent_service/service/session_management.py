import logging
import uuid
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class RealtimeSession:

    def __init__(self, client: WebSocket):
        self.session_id = str(uuid.uuid4())
        self.client = client

    async def listen(self):
        """Listen for messages from the websocket client"""
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
        # currently just log and echo
        logger.info("handling message: %s", message)
        await self.client.send_json({"echo": message})


class RealtimeSessionManager:
    _sessions: dict[str, RealtimeSession] = {}

    @classmethod
    def create(cls, client: WebSocket) -> RealtimeSession:
        session = RealtimeSession(client)
        cls._sessions[session.session_id] = session
        return session

    @classmethod
    def remove(cls, session: RealtimeSession):
        cls._sessions.pop(session.session_id, None)