import asyncio
from typing import Any

from fastapi import WebSocket

from dynamic_agent_service.util.setup_logging import get_my_logger

logger = get_my_logger()


class MonitorEventHub:
    _clients: set[WebSocket] = set()

    @classmethod
    async def connect(cls, websocket: WebSocket) -> None:
        await websocket.accept()
        cls._clients.add(websocket)

    @classmethod
    def disconnect(cls, websocket: WebSocket) -> None:
        cls._clients.discard(websocket)

    @classmethod
    async def publish(cls, event_type: str, payload: dict[str, Any]) -> None:
        if not cls._clients:
            return

        event = {"type": event_type, "payload": payload}
        disconnected: list[WebSocket] = []
        for client in cls._clients:
            try:
                await client.send_json(event)
            except Exception as exc:
                logger.warning("Failed to publish monitor event %s: %s", event_type, exc)
                disconnected.append(client)

        for client in disconnected:
            cls.disconnect(client)

    @classmethod
    def publish_nowait(cls, event_type: str, payload: dict[str, Any]) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(cls.publish(event_type, payload))


def session_event_payload(session) -> dict[str, Any]:
    return {
        "session_id": session.session_id,
        "setting": session.setting,
        "reconnect_keep": session.reconnect_keep,
        "disconnect_time": session.disconnect_time,
        "connected": session.client is not None and session.disconnect_time is None,
        "expired": session.is_expired(),
    }
