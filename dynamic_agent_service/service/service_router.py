import asyncio
import hashlib
import hmac
import os
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, Request, UploadFile, WebSocket
from pydantic import BaseModel, Field

from dynamic_agent_service.service.session_management import ChatAgentSession, SessionManager, TaskAgentSession
from dynamic_agent_service.agent.agent_structs import AgentState
from dynamic_agent_service.service.session_accessor import SessionAccessor
from dynamic_agent_service.service.media_storage import MediaStorage
from dynamic_agent_service.service.service_structs import (
    CreateSessionRequest,
    InitSubagentRequest,
    ToolResultRequest,
    TriggerSubagentRequest,
)
from dynamic_agent_service.logging.setup_logging import get_my_logger

logger = get_my_logger()

router = APIRouter()


class MemoryRequest(BaseModel):
    """Bind a memory operation to a pending tool call."""
    session_id: str
    runner_id: str
    trigger_id: str
    tool_call_id: str
    action: str
    checkpoint_id: str | None = None


@router.post("/memory")
async def memory(body: MemoryRequest):
    """Access memory through the active session and tool identity."""
    if body.action not in {"list", "check", "compact"}:
        raise HTTPException(status_code=422, detail="Unknown memory action")
    session = SessionManager.get(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if not isinstance(session, ChatAgentSession):
        raise HTTPException(status_code=409, detail="Memory requires a chat session")
    try:
        return await session.memory(body)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/create_session")
async def create_session(body: CreateSessionRequest, request: Request):
    try:
        session = await SessionManager.create(request=body)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if session.agi is None:
        await session.agent_setup()

    scheme = request.headers.get("x-forwarded-proto", "http")
    ws_scheme = "wss" if scheme == "https" else "ws"
    socket_url = f"{ws_scheme}://{request.headers['host']}/agent_session?session_id={session.session_id}"

    messages = await session.load_messages()
    return {
        "session_id": session.session_id,
        "session_type": session.session_type,
        "runner_id": session.agi.runner_id,
        "socket_url": socket_url,
        "messages": messages,
    }


@router.get("/sessions/{session_id}/messages")
async def session_messages(session_id: UUID, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                           history_token: str = Header(default="", alias="X-DA-History-Token")):
    """Read chat context using a server-issued session-bound authorization token."""
    secret = os.environ.get("DA_HISTORY_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="History authorization is not configured")
    identity = str(session_id)
    expected = hmac.new(secret.encode(), identity.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(history_token, expected):
        raise HTTPException(status_code=403, detail="History access denied")
    meta = await SessionAccessor.load_meta(identity)
    if meta is not None and meta.session_type != "chat":
        raise HTTPException(status_code=404, detail="Chat session not found")
    if meta is None and not await SessionAccessor.has_persisted_messages(identity):
        raise HTTPException(status_code=404, detail="Chat session not found")
    messages = await SessionAccessor.load_context(identity)
    return {"session_id": identity, "scope": "current_context",
            "system_prompt": meta.setting if meta else None,
            "items": [item.public_message() for item in messages[offset:offset + limit]],
            "total": len(messages),
            "next_offset": offset + limit if offset + limit < len(messages) else None}


@router.post("/tool_result")
async def tool_result(body: ToolResultRequest):
    session = SessionManager.get(body.session_id)
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
    session = SessionManager.get(body.session_id)
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
    session = SessionManager.get(body.session_id)
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
    session = SessionManager.get(session_id)
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
            await SessionManager.mark_disconnected(session)
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
    session = SessionManager.get(body.session_id)
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
    session = SessionManager.get(body.session_id)
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
    session = SessionManager.get(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.state is not AgentState.IDLE:
        raise HTTPException(status_code=409, detail=f"Session is {session.state}")
    trigger_id = body.trigger_id or uuid4().hex
    session.start_trigger(body.text, trigger_id)
    return {"status": "accepted", "trigger_id": trigger_id}


@router.post("/trigger_media")
async def trigger_media(
    session_id: str = Form(...),
    text: str = Form(""),
    trigger_id: str | None = Form(None, pattern=r"^[a-zA-Z0-9_-]{1,128}$"),
    images: list[UploadFile] = File(...),
):
    """Accept raw image uploads and start one multimodal turn."""
    session = SessionManager.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.state is not AgentState.IDLE:
        raise HTTPException(status_code=409, detail=f"Session is {session.state}")
    accepted_trigger_id = trigger_id or uuid4().hex
    stored_images = []
    try:
        if isinstance(session, TaskAgentSession):
            stored_images = await session.cache_images(images)
        else:
            stored_images = await MediaStorage.save_uploads(images)
        session.start_trigger(text, accepted_trigger_id, images=stored_images)
    except ValueError as exc:
        await MediaStorage.delete(stored_images)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except BaseException:
        await MediaStorage.delete(stored_images)
        raise
    return {"status": "accepted", "trigger_id": accepted_trigger_id}


@router.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """
    Delete persisted chat messages for a session and remove the live session if present.
    """
    session = SessionManager.get(session_id)
    if session is not None:
        await session.stop()
    if session is not None and session.client is not None:
        client = session.client
        session.client = None
        try:
            await client.close()
        except Exception as e:
            logger.warning("Failed to close websocket for session %s: %s", session_id, e)
    SessionManager._sessions.pop(session_id, None)
    if isinstance(session, TaskAgentSession):
        await session.expire_cache()
    else:
        await SessionAccessor.delete_session(session_id)
    return {"status": "ok", "session_id": session_id}



@router.websocket("/echo")
async def echo(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_text()
        await websocket.send_text(data)
