"""
Smoke test duplicate knowledge inbound into the same bucket.

The script inbounds the same small game article twice through the service API,
prints the stored blueprints and instances after each pass, and leaves workflow
logs in the configured cache folder while deleting the test bucket afterwards.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from dynamic_agent_client import DynamicAgentClient
from dynamic_agent_client.service_handler import ServiceHandler
from dynamic_agent_service.external_service.milvus_instance import MilvusInstance
from dynamic_agent_service.external_service.pg_instance import PgInstance
from dynamic_agent_service.knowledge.knowledge_accessor import KnowledgeAccessor

load_dotenv()


BUCKET_NAME = "smoke-knowledge-inbound-twice"
RESOURCE_PATH = Path(__file__).parent / "resource" / "smoke_inbound_text.txt"


async def dump_bucket(bucket_name: str, label: str) -> tuple[int, int]:
    print(f"\n===== {label} =====")
    blueprints = await KnowledgeAccessor.get_blueprint_list(bucket_name)
    print(f"blueprints: {len(blueprints)}")

    total_instances = 0
    sparse_instances = 0
    dump = {
        "label": label,
        "bucket_name": bucket_name,
        "blueprints": [],
    }
    for blueprint_index, blueprint in enumerate(blueprints, 1):
        print(f"\n=== Blueprint {blueprint_index}: {blueprint.name} ===")
        print(f"description: {blueprint.description}")
        print("attributes:")
        blueprint_dump = {
            "blueprint_id": blueprint.blueprint_id,
            "name": blueprint.name,
            "description": blueprint.description,
            "attributes": {},
            "instances": [],
        }
        for attr_name, attr_schema in blueprint.attributes.items():
            identifier = " identifier" if attr_schema.is_identifier else ""
            print(f"  - {attr_name}{identifier}: {attr_schema.description}")
            blueprint_dump["attributes"][attr_name] = {
                "description": attr_schema.description,
                "is_identifier": attr_schema.is_identifier,
            }

        instances = await wait_for_filled_instances(blueprint.blueprint_id)
        total_instances += len(instances)
        sparse_instances += sum(1 for instance in instances if len(instance) <= 1)
        blueprint_dump["instances"] = instances
        print(f"instances: {len(instances)}")
        for instance_index, instance in enumerate(instances, 1):
            print(f"\n  --- Instance {instance_index} ---")
            print(json.dumps(instance, ensure_ascii=False, indent=2))
        dump["blueprints"].append(blueprint_dump)

    print(f"\ntotal_instances: {total_instances}")
    print(f"sparse_instances: {sparse_instances}")
    dump["total_instances"] = total_instances
    dump["sparse_instances"] = sparse_instances
    write_bucket_dump(bucket_name, label, dump)
    return len(blueprints), total_instances, sparse_instances


def write_bucket_dump(bucket_name: str, label: str, dump: dict):
    cache_dir = Path(os.getenv("CACHE_DIR", "./cache"))
    dump_dir = cache_dir / "bucket" / bucket_name / "dumps"
    dump_dir.mkdir(parents=True, exist_ok=True)
    dump_path = dump_dir / f"{label.lower().replace(' ', '_')}.json"
    dump_path.write_text(json.dumps(dump, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"bucket dump written: {dump_path}")


async def wait_for_filled_instances(blueprint_id: str, attempts: int = 6, delay: float = 2.0) -> list[dict]:
    instances = []
    for attempt in range(attempts):
        instances = await KnowledgeAccessor.get_filled_instances_by_blueprint(blueprint_id)
        if instances and all(len(instance) > 1 for instance in instances):
            return instances
        if attempt < attempts - 1:
            await asyncio.sleep(delay)
    return instances


async def inbound_once(knowledge_text: str, pass_name: str):
    instruction_query = "Find the two games mentioned in the text."
    print(f"\n{pass_name}: inbounding knowledge...")
    result = await DynamicAgentClient.inbound(
        instruction_query=instruction_query,
        knowledge_text=knowledge_text,
        bucket_name=BUCKET_NAME,
    )
    print(f"{pass_name}: inbound_result: {result}")
    return result


async def main():
    await PgInstance.initialize()
    MilvusInstance.initialize()

    try:
        knowledge_text = RESOURCE_PATH.read_text(encoding="utf-8")
        print(f"resource: {RESOURCE_PATH}")
        print(f"characters: {len(knowledge_text)}")
        print(f"cache_dir: {os.getenv('CACHE_DIR', './cache')}")

        port = os.getenv("PORT", "7777")
        await DynamicAgentClient.connect(server_addr=f"http://localhost:{port}")

        existing = await DynamicAgentClient.check_bucket(BUCKET_NAME)
        if existing["exists"]:
            print(f"deleting existing bucket: {BUCKET_NAME}")
            await DynamicAgentClient.delete_bucket(BUCKET_NAME)

        print(f"creating bucket: {BUCKET_NAME}")
        await DynamicAgentClient.create_bucket(
            name=BUCKET_NAME,
            description="Smoke test bucket for duplicate inbound",
        )

        first_result = await inbound_once(knowledge_text, "first pass")
        _, first_total, first_sparse = await dump_bucket(BUCKET_NAME, "after first pass")

        second_result = await inbound_once(knowledge_text, "second pass")
        _, second_total, second_sparse = await dump_bucket(BUCKET_NAME, "after second pass")

        assert first_result["status"] == "ok"
        assert second_result["status"] == "ok"
        assert first_total == 2, "expected first inbound to store two game instances"
        assert second_total == 2, "expected duplicate inbound to detect collisions and keep two instances"
        assert first_sparse == 0, "expected first inbound instances to have filled attributes"
        assert second_sparse == 0, "expected second inbound instances to have filled attributes"

        print("\nALL PASSED")
    finally:
        try:
            existing = await DynamicAgentClient.check_bucket(BUCKET_NAME)
            if existing["exists"]:
                print(f"\ndeleting test bucket: {BUCKET_NAME}")
                await DynamicAgentClient.delete_bucket(BUCKET_NAME)
        finally:
            await ServiceHandler.stop()
            MilvusInstance.close()
            await PgInstance.close()


if __name__ == "__main__":
    asyncio.run(main())
