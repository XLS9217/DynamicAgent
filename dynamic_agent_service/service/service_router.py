from fastapi import APIRouter, WebSocket, HTTPException, Request
from pydantic import BaseModel
import logging

from dynamic_agent_service.service.session_management import RealtimeSessionManager

logger = logging.getLogger(__name__)

router = APIRouter()


class CreateSessionRequest(BaseModel):
    setting: str

@router.post("/create_session")
async def create_session(body: CreateSessionRequest, request: Request):
    session = RealtimeSessionManager.create(setting=body.setting)
    await session.agent_setup()
    socket_url = f"ws://{request.headers['host']}/agent_session?session_id={session.session_id}"
    return {"session_id": session.session_id, "socket_url": socket_url}


@router.websocket("/agent_session")
async def agent_session(websocket: WebSocket, session_id: str):
    logger.info("WebSocket request received for session %s", session_id)
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

@router.post("/agent_operator")
async def register_operator():
    """
    should come with a session_id and a serialized operator json
    get the session and add the operator
    """

@router.websocket("/echo")
async def echo(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_text()
        await websocket.send_text(data)