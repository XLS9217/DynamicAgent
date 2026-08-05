from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException

from dynamic_agent_service.external_service.openai_resource_accessor import (
    OpenAIResourceAccessor,
)
from dynamic_agent_service.external_service.openai_resource_structs import (
    OpenAIResourceCreate,
    OpenAIResourceUpdate,
)
from dynamic_agent_service.knowledge.knowledge_accessor import KnowledgeAccessor
from dynamic_agent_service.util.log_accessor import (
    clear_session_logs,
    clear_system_log,
    list_log_files,
    read_log_file,
)
from dynamic_agent_service.service.monitor_events import MonitorEventHub
from dynamic_agent_service.service.session_management import RealtimeSession, RealtimeSessionManager
from dynamic_agent_service.util.setup_logging import get_my_logger

logger = get_my_logger()

router = APIRouter()


def _mask_api_key(api_key: str) -> str:
    if len(api_key) <= 4:
        return "••••"
    return f"••••{api_key[-4:]}"


def _resource_payload(resource) -> dict:
    return {
        "resource_id": resource.resource_id,
        "model": resource.model,
        "api_key": _mask_api_key(resource.api_key),
        "base_url": resource.base_url,
        "enabled": resource.enabled,
        "priority": resource.priority,
    }


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


@router.get("/monitor/openai-resources")
async def list_openai_resources():
    resources = await OpenAIResourceAccessor.list_resources(enabled_only=False)
    return {"status": "ok", "resources": [_resource_payload(resource) for resource in resources]}


@router.post("/monitor/openai-resources")
async def create_openai_resource(resource: OpenAIResourceCreate):
    created = await OpenAIResourceAccessor.create_resource(resource)
    await MonitorEventHub.publish(
        "openai_resource_created",
        {"resource_id": created.resource_id},
    )
    return {"status": "ok", "resource": _resource_payload(created)}


@router.put("/monitor/openai-resources/{resource_id}")
async def update_openai_resource(resource_id: str, update: OpenAIResourceUpdate):
    if update.api_key == "":
        update.api_key = None
    resource = await OpenAIResourceAccessor.update_resource(resource_id, update)
    if resource is None:
        raise HTTPException(status_code=404, detail="OpenAI resource not found")
    await MonitorEventHub.publish("openai_resource_updated", {"resource_id": resource_id})
    return {"status": "ok", "resource": _resource_payload(resource)}


@router.delete("/monitor/openai-resources/{resource_id}")
async def delete_openai_resource(resource_id: str):
    if not await OpenAIResourceAccessor.delete_resource(resource_id):
        raise HTTPException(status_code=404, detail="OpenAI resource not found")
    await MonitorEventHub.publish("openai_resource_deleted", {"resource_id": resource_id})
    return {"status": "ok", "resource_id": resource_id}


@router.get("/monitor/logs")
async def get_logs():
    return {"status": "ok", "files": list_log_files()}


@router.get("/monitor/logs/content")
async def get_log_content(path: str):
    try:
        content = await read_log_file(path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Log file not found")
    return {"status": "ok", **content}


@router.delete("/monitor/logs/system")
async def delete_system_log_content():
    if not await clear_system_log():
        raise HTTPException(status_code=404, detail="System log not found")
    return {"status": "ok"}


@router.delete("/monitor/logs/sessions/{session_id}")
async def delete_session_log_content(session_id: str):
    deleted = await clear_session_logs(session_id)
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Session logs not found")
    return {"status": "ok", "deleted": deleted}


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
