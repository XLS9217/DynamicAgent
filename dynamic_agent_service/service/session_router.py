from fastapi import APIRouter, WebSocket
import logging
from dynamic_agent_service.service.session_management import RealtimeSessionManager

logger = logging.getLogger(__name__)

router = APIRouter()

@router.websocket("/agent_session")
async def agent_session(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket connection established")
    session = RealtimeSessionManager.create(websocket)
    try:
        await session.listen()
    finally:
        RealtimeSessionManager.remove(session)
        logger.info("WebSocket connection cleaned up")