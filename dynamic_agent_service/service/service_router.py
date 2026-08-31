import asyncio

from fastapi import APIRouter, WebSocket, HTTPException, Request
from pydantic import BaseModel

from dynamic_agent_service.service.session_management import RealtimeSessionManager
from dynamic_agent_service.agent.agent_structs import AgentState
from dynamic_agent_service.service.session_accessor import SessionAccessor
from dynamic_agent_service.service.monitor_events import MonitorEventHub, session_event_payload
from dynamic_agent_service.service.service_structs import (
    CreateSessionRequest,
    InitSubagentRequest,
    ToolResultRequest,
    TriggerSubagentRequest,
)
from dynamic_agent_service.knowledge.knowledge_interface import KnowledgeInterface
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
    bucket_name: str | None = None

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
    session.active_trigger_task = asyncio.create_task(session.trigger_agent(body.text, bucket_name=body.bucket_name))
    return {"status": "accepted"}


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
    if session is not None:
        await MonitorEventHub.publish("session_deleted", session_event_payload(session))
    return {"status": "ok", "session_id": session_id}



@router.websocket("/echo")
async def echo(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_text()
        await websocket.send_text(data)


class CreateBucketRequest(BaseModel):
    name: str
    description: str = ""

@router.post("/knowledge/bucket")
async def create_bucket(body: CreateBucketRequest):
    await KnowledgeInterface.create_bucket(body.name, body.description)
    return {"status": "ok", "bucket_name": body.name}


@router.get("/knowledge/bucket/{bucket_name}")
async def check_bucket(bucket_name: str):
    exists = await KnowledgeInterface.check_bucket(bucket_name)
    return {"status": "ok", "exists": exists}


@router.delete("/knowledge/bucket/{bucket_name}")
async def delete_bucket(bucket_name: str):
    message = await KnowledgeInterface.delete_bucket(bucket_name)
    return {"status": "ok", "message": message}


class KnowledgeRetrieveRequest(BaseModel):
    query: str
    bucket_name: str
    top_k: int = 10
    score_threshold: float = 0.3

@router.post("/knowledge/retrieve")
async def knowledge_retrieve(body: KnowledgeRetrieveRequest):
    retrieve_result = await KnowledgeInterface.retrieve(
        query=body.query,
        bucket_name=body.bucket_name,
        top_k=body.top_k,
        score_threshold=body.score_threshold
    )
    return {
        "status": "ok",
        "results": retrieve_result["results"],
        "analytics": retrieve_result["analytics"],
    }


class KnowledgeExpandRequest(BaseModel):
    bucket_name: str
    node_ids: list[str]

@router.post("/knowledge/expand")
async def knowledge_expand(body: KnowledgeExpandRequest):
    results = await KnowledgeInterface.expand_node_ids(
        bucket_name=body.bucket_name,
        node_ids=body.node_ids,
    )
    return {"status": "ok", "results": results}
