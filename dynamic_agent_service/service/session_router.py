from fastapi import APIRouter, WebSocket, HTTPException
from pydantic import BaseModel
import logging

from dynamic_agent_service.service.session_management import RealtimeSessionManager

logger = logging.getLogger(__name__)

router = APIRouter()


class CreateSessionRequest(BaseModel):
    setting: str


@router.post("/create_session")
async def create_session(body: CreateSessionRequest):
    session = RealtimeSessionManager.create(setting=body.setting)
    await session.agent_setup()
    return {"session_id": session.session_id}


@router.websocket("/agent_session")
async def agent_session(websocket: WebSocket, session_id: str):
    session = RealtimeSessionManager.get(session_id)
    if session is None:
        await websocket.close(code=4004)
        return

    await websocket.accept()
    session.attach_websocket(websocket)
    logger.info("WebSocket connected for session %s", session_id)
    try:
        await session.listen()
    finally:
        RealtimeSessionManager.remove(session)
        logger.info("WebSocket cleaned up for session %s", session_id)