import asyncio
from uuid import uuid4

from fastapi import APIRouter, WebSocket, HTTPException, Request
from pydantic import BaseModel, Field

from dynamic_agent_service.service.session_management import RealtimeSessionManager
from dynamic_agent_service.agent.agent_structs import AgentState
from dynamic_agent_service.service.session_accessor import SessionAccessor
from dynamic_agent_service.service.service_structs import (
    CreateSessionRequest,
    InitSubagentRequest,
    ToolResultRequest,
    TriggerSubagentRequest,
)
from dynamic_agent_service.logging.setup_logging import get_my_logger

logger = get_my_logger()

router = APIRouter()

@router.post("/create_session")
async def create_session(body: CreateSessionRequest, request: Request):
    session = await RealtimeSessionManager.create(request=body)
    await session.agent_setup()

    scheme = request.headers.get("x-forwarded-proto", "http")
    ws_scheme = "wss" if scheme == "https" else "ws"
    socket_url = f"{ws_scheme}://{request.headers['host']}/agent_session?session_id={session.session_id}"

    messages = await session.load_messages()
    return {
        "session_id": session.session_id,
        "runner_id": session.agi.runner_id,
        "socket_url": socket_url,
        "messages": messages,
    }


@router.post("/tool_result")
async def tool_result(body: ToolResultRequest):
    session = RealtimeSessionManager.get(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.accepts_trigger(body.trigger_id):
        return {"status": "ignored"}
    try:
        await session.receive_tool_result(
            tool_call_id=body.tool_call_id,
            ok=body.ok,
            result=body.result,
            runner_id=body.runner_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"status": "ok"}


@router.post("/init_subagent")
async def init_subagent(body: InitSubagentRequest):
    session = RealtimeSessionManager.get(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.accepts_trigger(body.trigger_id):
        raise HTTPException(status_code=409, detail="Turn is no longer active")
    try:
        runner_id = session.init_subagent(
            parent_runner_id=body.parent_runner_id,
            name=body.name,
            setting=body.setting,
            operators=body.operators,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"status": "ok", "runner_id": runner_id, "name": body.name}


@router.post("/trigger_subagent")
async def trigger_subagent(body: TriggerSubagentRequest):
    session = RealtimeSessionManager.get(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.accepts_trigger(body.trigger_id):
        return {"status": "ignored"}
    try:
        await session.trigger_subagent(
            parent_runner_id=body.parent_runner_id,
            parent_tool_call_id=body.parent_tool_call_id,
            runner_id=body.runner_id,
            task=body.task,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"status": "accepted"}


@router.websocket("/agent_session")
async def agent_session(websocket: WebSocket, session_id: str):
    logger.info("WebSocket request received for session %s", session_id)
    session = RealtimeSessionManager.get(session_id)
    if session is None:
        await websocket.close(code=4004)
        return

    await websocket.accept()
    await session.attach_websocket(websocket)
    logger.info("WebSocket connected for session %s", session_id)
    try:
        await session.listen()
    finally:
        # Only mark disconnected if this websocket is still the active one
        if session.client is websocket:
            RealtimeSessionManager.mark_disconnected(session)
            logger.info("WebSocket cleaned up for session %s", session_id)
        else:
            logger.info("WebSocket was replaced for session %s, skipping disconnect", session_id)



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


class TriggerRequest(BaseModel):
    session_id: str
    text: str
    trigger_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,128}$")


class StopRequest(BaseModel):
    """Identify the session turn to cancel without closing its connection."""
    session_id: str
    trigger_id: str | None = None


@router.post("/stop")
async def stop(body: StopRequest):
    """Stop the requested turn; repeated or outdated requests do nothing."""
    session = RealtimeSessionManager.get(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    completion = await session.stop(body.trigger_id)
    return {
        "status": ("stopped" if completion.cancelled else "completed") if completion else "idle",
        "trigger_id": completion.trigger_id if completion else body.trigger_id,
        "completion": completion.model_dump(exclude_none=True) if completion else None,
    }

@router.post("/trigger")
async def trigger(body: TriggerRequest):
    """
    Trigger agent with text input. Response streams via WebSocket.
    """
    session = RealtimeSessionManager.get(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.state is not AgentState.IDLE:
        raise HTTPException(status_code=409, detail=f"Session is {session.state}")
    trigger_id = body.trigger_id or uuid4().hex
    session.start_trigger(body.text, trigger_id)
    return {"status": "accepted", "trigger_id": trigger_id}


@router.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """
    Delete persisted chat messages for a session and remove the live session if present.
    """
    session = RealtimeSessionManager.get(session_id)
    if session is not None and session.client is not None:
        client = session.client
        session.client = None
        try:
            await client.close()
        except Exception as e:
            logger.warning("Failed to close websocket for session %s: %s", session_id, e)
    RealtimeSessionManager._sessions.pop(session_id, None)
    await SessionAccessor.delete_session(session_id)
    return {"status": "ok", "session_id": session_id}



@router.websocket("/echo")
async def echo(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_text()
        await websocket.send_text(data)
