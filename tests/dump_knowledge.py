import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from dynamic_agent_service.external_service.pg_instance import PgInstance
from dynamic_agent_service.knowledge.blueprint_accessor import BlueprintAccessor
from dynamic_agent_service.knowledge.knowledge_node_accessor import KnowledgeNodeAccessor


async def dump_to_cache(cache_dir: str, bucket_name: str = "test"):
    # Create bucket-specific folder
    bucket_dir = Path(cache_dir) / bucket_name
    bucket_dir.mkdir(parents=True, exist_ok=True)

    # Dump blueprints
    blueprints = await BlueprintAccessor.get_blueprint_list(bucket_name)
    bp_result = [bp.model_dump() for bp in blueprints]

    bp_path = bucket_dir / "knowledge_dump.json"
    with open(bp_path, "w", encoding="utf-8") as f:
        json.dump(bp_result, f, ensure_ascii=False, indent=2)
    print(f"Dumped {len(bp_result)} blueprints to {bp_path}")

    # Dump instances with attribute values from Milvus
    instances = await BlueprintAccessor.get_all_instances(bucket_name)
    instance_result = []
    for inst in instances:
        row_ids = [a["row_id"] for a in inst["attributes"]]
        entities = KnowledgeNodeAccessor.get_by_ids(bucket_name, row_ids) if row_ids else []
        value_map = {e["id"]: e["value"] for e in entities}

        obj = {
            "instance_id": inst["instance_id"],
            "blueprint_id": inst["blueprint_id"],
            "attributes": {
                a["attr_name"]: value_map.get(a["row_id"])
                for a in inst["attributes"]
            },
        }
        instance_result.append(obj)

    inst_path = bucket_dir / "instance_dump.json"
    with open(inst_path, "w", encoding="utf-8") as f:
        json.dump(instance_result, f, ensure_ascii=False, indent=2)
    print(f"Dumped {len(instance_result)} instances to {inst_path}")


async def main():
    load_dotenv()
    await PgInstance.initialize()

    cache_dir = os.getenv("CACHE_DIR", ".")
    os.makedirs(cache_dir, exist_ok=True)
    await dump_to_cache(cache_dir)

    await PgInstance.close()


if __name__ == "__main__":
    asyncio.run(main())
