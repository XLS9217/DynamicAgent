from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException

from dynamic_agent_service.knowledge.knowledge_accessor import KnowledgeAccessor
from dynamic_agent_service.service.monitor_events import MonitorEventHub
from dynamic_agent_service.service.session_management import RealtimeSession, RealtimeSessionManager
from dynamic_agent_service.util.setup_logging import get_my_logger

logger = get_my_logger()

router = APIRouter()


@router.websocket("/monitor/events")
async def monitor_events(websocket: WebSocket):
    await MonitorEventHub.connect(websocket)
    try:
        await websocket.send_json({"type": "monitor_connected", "payload": {"status": "ok"}})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("Monitor websocket disconnected")
    finally:
        MonitorEventHub.disconnect(websocket)


async def _session_summary(session: RealtimeSession) -> dict:
    messages = await session.load_messages()
    return {
        "session_id": session.session_id,
        "setting": session.setting,
        "reconnect_keep": session.reconnect_keep,
        "disconnect_time": session.disconnect_time,
        "connected": session.client is not None and session.disconnect_time is None,
        "expired": session.is_expired(),
        "message_count": len(messages),
    }


@router.get("/monitor/sessions")
async def list_sessions():
    sessions = [
        await _session_summary(session)
        for session in RealtimeSessionManager._sessions.values()
    ]
    return {"status": "ok", "sessions": sessions}


@router.get("/monitor/sessions/{session_id}")
async def get_session(session_id: str):
    session = RealtimeSessionManager.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    metadata = await _session_summary(session)
    messages = await session.load_messages()
    rag = await session.get_rag()
    return {
        "status": "ok",
        "session": metadata,
        "messages": messages,
        "rag": rag.model_dump() if rag is not None else None,
    }


@router.get("/session/{session_id}/rag")
async def get_session_rag(session_id: str):
    """Fetch the last RAG-retrieved knowledge for a session (monitoring)."""
    session = RealtimeSessionManager.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    rag = await session.get_rag()
    if rag is None:
        return {"status": "ok", "rag": None}
    return {"status": "ok", "rag": rag.model_dump()}


@router.get("/buckets")
async def list_buckets():
    buckets = await KnowledgeAccessor.get_bucket_list()
    return {
        "status": "ok",
        "buckets": [{"name": b.name, "description": b.description} for b in buckets]
    }


@router.get("/buckets/{bucket_name}")
async def get_bucket(bucket_name: str):
    bucket = await KnowledgeAccessor.get_bucket(bucket_name)
    if bucket is None:
        raise HTTPException(status_code=404, detail="Bucket not found")
    return {
        "status": "ok",
        "bucket": {"name": bucket.name, "description": bucket.description}
    }


@router.get("/buckets/{bucket_name}/blueprints")
async def list_blueprints(bucket_name: str):
    bucket = await KnowledgeAccessor.get_bucket(bucket_name)
    if bucket is None:
        raise HTTPException(status_code=404, detail="Bucket not found")

    blueprints = await KnowledgeAccessor.get_blueprint_list(bucket_name)
    return {
        "status": "ok",
        "blueprints": [
            {
                "id": bp.blueprint_id,
                "name": bp.name,
                "description": bp.description,
                "attributes": {
                    attr_name: {
                        "description": attr_schema.description,
                        "is_identifier": attr_schema.is_identifier
                    }
                    for attr_name, attr_schema in bp.attributes.items()
                }
            }
            for bp in blueprints
        ]
    }


@router.get("/blueprints/{blueprint_id}/instances")
async def list_instances_by_blueprint(blueprint_id: str):
    blueprint = await KnowledgeAccessor.get_blueprint(blueprint_id)
    if blueprint is None:
        raise HTTPException(status_code=404, detail="Blueprint not found")

    instances = await KnowledgeAccessor.get_filled_instances_by_blueprint(blueprint_id)
    return {
        "status": "ok",
        "blueprint_id": blueprint_id,
        "instances": instances
    }
