"""
Smoke test knowledge inbound from the Claude Mythos resource.

The script creates a deterministic test bucket through the SDK, inbounds the
resource text through the service API, directly fetches and prints all stored
blueprints and filled instances, then deletes the test bucket.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
from dynamic_agent_client import DynamicAgentClient
from dynamic_agent_client.service_handler import ServiceHandler
from dynamic_agent_service.external_service.milvus_instance import MilvusInstance
from dynamic_agent_service.external_service.pg_instance import PgInstance
from dynamic_agent_service.knowledge.knowledge_accessor import KnowledgeAccessor

load_dotenv()


BUCKET_NAME = "smoke-knowledge-inbound"
RESOURCE_PATH = Path(__file__).parent.parent / "resource" / "smoke_inbound_text.txt"
SOURCE_METADATA = {"source": RESOURCE_PATH.name}


async def print_inbounded_content(bucket_name: str):
    blueprints = await KnowledgeAccessor.get_blueprint_list(bucket_name)
    print(f"\nblueprints: {len(blueprints)}")

    total_instances = 0
    for blueprint_index, blueprint in enumerate(blueprints, 1):
        print(f"\n=== Blueprint {blueprint_index}: {blueprint.name} ===")
        print(f"description: {blueprint.description}")
        print("attributes:")
        for attr_name, attr_schema in blueprint.attributes.items():
            identifier = " identifier" if attr_schema.is_identifier else ""
            print(f"  - {attr_name}{identifier}: {attr_schema.description}")

        instances = await KnowledgeAccessor.get_filled_instances_by_blueprint(blueprint.blueprint_id)
        total_instances += len(instances)
        print(f"instances: {len(instances)}")
        for instance_index, instance in enumerate(instances, 1):
            print(f"\n  --- Instance {instance_index} ---")
            print(json.dumps(instance, ensure_ascii=False, indent=2))
            sources = await KnowledgeAccessor.get_sources_by_instance(instance["instance_id"])
            print("  sources:")
            print(json.dumps([source.source_metadata for source in sources], ensure_ascii=False, indent=2))

    print(f"\ntotal_instances: {total_instances}")
    return blueprints, total_instances


async def main():
    await PgInstance.initialize()
    MilvusInstance.initialize()

    try:
        knowledge_text = RESOURCE_PATH.read_text(encoding="utf-8")
        print(f"resource: {RESOURCE_PATH}")
        print(f"characters: {len(knowledge_text)}")

        port = os.getenv("PORT", "7777")
        await DynamicAgentClient.connect(server_addr=f"http://localhost:{port}")

        existing = await DynamicAgentClient.check_bucket(BUCKET_NAME)
        if existing["exists"]:
            print(f"deleting existing bucket: {BUCKET_NAME}")
            await DynamicAgentClient.delete_bucket(BUCKET_NAME)

        print(f"creating bucket: {BUCKET_NAME}")
        await DynamicAgentClient.create_bucket(
            name=BUCKET_NAME,
            description="Smoke test bucket for Claude Mythos inbound",
        )

        instruction_query = "Find the two games mentioned in the text."
        print("inbounding knowledge...")
        inbound_result = await DynamicAgentClient.inbound(
            instruction_query=instruction_query,
            knowledge_text=knowledge_text,
            bucket_name=BUCKET_NAME,
            source_metadata=SOURCE_METADATA,
        )
        print(f"inbound_result: {inbound_result}")

        blueprints, total_instances = await print_inbounded_content(BUCKET_NAME)
        assert blueprints, "expected at least one blueprint to be inbounded"
        assert total_instances > 0, "expected at least one filled instance to be inbounded"

        inbounded_source_metadata = []
        for blueprint in blueprints:
            instances = await KnowledgeAccessor.get_filled_instances_by_blueprint(blueprint.blueprint_id)
            for instance in instances:
                sources = await KnowledgeAccessor.get_sources_by_instance(instance["instance_id"])
                inbounded_source_metadata.extend(source.source_metadata for source in sources)

        assert any(
            source_metadata.get("source") == RESOURCE_PATH.name
            for source_metadata in inbounded_source_metadata
        ), f"expected inbound source metadata with source={RESOURCE_PATH.name}"

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
