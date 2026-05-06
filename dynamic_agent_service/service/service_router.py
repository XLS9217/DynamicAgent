from fastapi import APIRouter, WebSocket, HTTPException, Request
from pydantic import BaseModel

from dynamic_agent_service.service.session_management import RealtimeSessionManager
from dynamic_agent_service.service.service_structs import CreateSessionRequest
from dynamic_agent_service.knowledge.knowledge_interface import KnowledgeInterface
from dynamic_agent_service.util.setup_logging import get_my_logger

logger = get_my_logger()

router = APIRouter()

@router.post("/create_session")
async def create_session(body: CreateSessionRequest, request: Request):
    webhook_url = f"http://{request.client.host}:{body.webhook_port}/webhook"
    session = RealtimeSessionManager.create(request=body, webhook_url=webhook_url)
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
        RealtimeSessionManager.mark_disconnected(session)
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


class TriggerRequest(BaseModel):
    session_id: str
    text: str

@router.post("/trigger")
async def trigger(body: TriggerRequest):
    """
    Trigger agent with text input. Response streams via WebSocket.
    """
    session = RealtimeSessionManager.get(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await session.trigger_agent(body.text)
    return {"status": "accepted"}



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


class KnowledgeInboundRequest(BaseModel):
    instruction_query: str
    knowledge_text: str
    bucket_name: str

@router.post("/knowledge/inbound")
async def knowledge_inbound(body: KnowledgeInboundRequest):
    result = await KnowledgeInterface.inbound(
        instruction_query=body.instruction_query,
        knowledge_text=body.knowledge_text,
        bucket_name=body.bucket_name
    )
    return {"status": "ok", "message": result}


class KnowledgeRetrieveRequest(BaseModel):
    query: str
    bucket_name: str
    top_k: int = 10
    score_threshold: float = 0.3

@router.post("/knowledge/retrieve")
async def knowledge_retrieve(body: KnowledgeRetrieveRequest):
    results = await KnowledgeInterface.retrieve(
        query=body.query,
        bucket_name=body.bucket_name,
        top_k=body.top_k,
        score_threshold=body.score_threshold
    )
    return {"status": "ok", "results": results}