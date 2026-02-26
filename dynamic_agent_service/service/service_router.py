from fastapi import APIRouter, WebSocket, HTTPException, Request
from pydantic import BaseModel

from dynamic_agent_service.service.session_management import RealtimeSessionManager
from dynamic_agent_service.util.setup_logging import get_my_logger

logger = get_my_logger()

router = APIRouter()


class CreateSessionRequest(BaseModel):
    setting: str

@router.post("/create_session")
async def create_session(body: CreateSessionRequest, request: Request):

    session = RealtimeSessionManager.create(setting=body.setting)
    await session.agent_setup()

    scheme = request.headers.get("x-forwarded-proto", "http")
    ws_scheme = "wss" if scheme == "https" else "ws"
    socket_url = f"{ws_scheme}://{request.headers['host']}/agent_session?session_id={session.session_id}"

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



class RegisterOperatorRequest(BaseModel):
    session_id: str
    operator: dict

@router.post("/agent_operator")
async def register_operator(body: RegisterOperatorRequest):
    """
    Receives a session_id and a serialized operator, registers it on the session's AGI.
    """
    session = RealtimeSessionManager.get(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    session.register_operator(body.operator)
    return {"status": "ok", "operator_name": body.operator.get("name")}



@router.websocket("/echo")
async def echo(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_text()
        await websocket.send_text(data)