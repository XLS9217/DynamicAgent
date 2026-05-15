from fastapi import APIRouter, HTTPException

from dynamic_agent_service.knowledge.knowledge_accessor import KnowledgeAccessor
from dynamic_agent_service.util.setup_logging import get_my_logger

logger = get_my_logger()

router = APIRouter()


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