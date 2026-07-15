"""
Smoke test inbound with use_existing_blueprint=True.

Expected behavior:
1. A fresh bucket has no blueprints.
2. Inbound identifies an entity type but does not create a new blueprint.
3. The workflow log records an ERROR entry explaining that no matching blueprint
   was found while use_existing_blueprint=True.
4. After a matching blueprint is manually created, inbound reuses it and stores
   instances without creating another blueprint.
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
from dynamic_agent_service.knowledge.knowledge_structs import Blueprint, BlueprintAttributeSchema

load_dotenv()


BUCKET_NAME = "smoke-existing-blueprint-only"
RESOURCE_PATH = Path(__file__).parent.parent / "resource" / "smoke_inbound_text.txt"
INSTRUCTION_QUERY = "Extract the project meeting knowledge from this text."


def latest_inbound_log_path(bucket_name: str) -> Path:
    bucket_log_dir = Path(os.getenv("CACHE_DIR", "./cache")) / "bucket" / bucket_name
    inbound_logs = sorted(bucket_log_dir.glob("inbound_*.jsonl"), key=lambda p: p.stat().st_mtime)
    assert inbound_logs, f"expected inbound workflow log under {bucket_log_dir}"
    return inbound_logs[-1]


def read_log_messages(log_path: Path) -> list[str]:
    messages = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        message = record.get("message")
        if message:
            messages.append(message)
    return messages


async def create_meeting_blueprint() -> str:
    blueprint = Blueprint(
        bucket_name=BUCKET_NAME,
        name="Meeting",
        description="A project meeting with discussion notes, decisions, and action items.",
        attributes={
            "meeting_name": BlueprintAttributeSchema(
                description="The short human-readable name or title of the meeting.",
                is_identifier=True,
            ),
            "discussion_summary": BlueprintAttributeSchema(
                description="The main topics and context discussed during the meeting.",
            ),
            "decisions": BlueprintAttributeSchema(
                description="Important decisions, commitments, or agreements made in the meeting.",
            ),
            "action_items": BlueprintAttributeSchema(
                description="Follow-up tasks, owners, deadlines, and next steps from the meeting.",
            ),
        },
    )
    return await KnowledgeAccessor.create_blueprint(blueprint)


async def wait_for_instances(blueprint_id: str, attempts: int = 6, delay: float = 2.0) -> list[dict]:
    instances = []
    for attempt in range(attempts):
        instances = await KnowledgeAccessor.get_filled_instances_by_blueprint(blueprint_id)
        if instances and all(len(instance) > 1 for instance in instances):
            return instances
        if attempt < attempts - 1:
            await asyncio.sleep(delay)
    return instances


async def main():
    await PgInstance.initialize()
    MilvusInstance.initialize()

    try:
        knowledge_text = RESOURCE_PATH.read_text(encoding="utf-8")
        print(f"resource: {RESOURCE_PATH}")
        print(f"characters: {len(knowledge_text)}")
        print(f"instruction_query: {INSTRUCTION_QUERY}")
        print("use_existing_blueprint: True")

        port = os.getenv("PORT", "7777")
        await DynamicAgentClient.connect(server_addr=f"http://localhost:{port}")

        existing = await DynamicAgentClient.check_bucket(BUCKET_NAME)
        if existing["exists"]:
            print(f"deleting existing bucket: {BUCKET_NAME}")
            await DynamicAgentClient.delete_bucket(BUCKET_NAME)

        print(f"creating bucket: {BUCKET_NAME}")
        await DynamicAgentClient.create_bucket(
            name=BUCKET_NAME,
            description="Smoke test bucket for existing-blueprint-only inbound",
        )

        before_blueprints = await KnowledgeAccessor.get_blueprint_list(BUCKET_NAME)
        assert before_blueprints == [], "expected fresh bucket to start with no blueprints"

        print("\nphase 1: inbound without existing blueprint...")
        inbound_result = await DynamicAgentClient.inbound(
            instruction_query=INSTRUCTION_QUERY,
            knowledge_text=knowledge_text,
            bucket_name=BUCKET_NAME,
            entity_limit_one=True,
            use_existing_blueprint=True,
        )
        print(f"phase 1 inbound_result: {inbound_result}")

        after_blueprints = await KnowledgeAccessor.get_blueprint_list(BUCKET_NAME)
        print(f"blueprints after phase 1: {len(after_blueprints)}")

        log_path = latest_inbound_log_path(BUCKET_NAME)
        print(f"phase 1 inbound log: {log_path}")
        messages = read_log_messages(log_path)
        error_messages = [
            message for message in messages
            if "ERROR: No existing blueprint matched entity type" in message
        ]
        for message in error_messages:
            print(message)

        assert inbound_result["status"] == "ok"
        assert inbound_result["message"] == "Processed 0 entities successfully"
        assert after_blueprints == [], "expected no blueprint to be created"
        assert error_messages, "expected no-matching-blueprint error in workflow log"

        print("\nphase 2: create matching blueprint and inbound again...")
        meeting_blueprint_id = await create_meeting_blueprint()
        print(f"created blueprint: Meeting ({meeting_blueprint_id})")

        inbound_result = await DynamicAgentClient.inbound(
            instruction_query=INSTRUCTION_QUERY,
            knowledge_text=knowledge_text,
            bucket_name=BUCKET_NAME,
            entity_limit_one=True,
            use_existing_blueprint=True,
        )
        print(f"phase 2 inbound_result: {inbound_result}")

        final_blueprints = await KnowledgeAccessor.get_blueprint_list(BUCKET_NAME)
        print(f"blueprints after phase 2: {len(final_blueprints)}")
        for blueprint in final_blueprints:
            print(f"  - {blueprint.name} ({blueprint.blueprint_id})")

        phase_2_log_path = latest_inbound_log_path(BUCKET_NAME)
        print(f"phase 2 inbound log: {phase_2_log_path}")
        phase_2_messages = read_log_messages(phase_2_log_path)
        phase_2_errors = [
            message for message in phase_2_messages
            if "ERROR: No existing blueprint matched entity type" in message
        ]
        reuse_messages = [
            message for message in phase_2_messages
            if message == "Reusing blueprint: Meeting"
        ]

        instances = await wait_for_instances(meeting_blueprint_id)
        print(f"instances after phase 2: {len(instances)}")
        for instance in instances:
            print(json.dumps(instance, ensure_ascii=False, indent=2))

        assert inbound_result["status"] == "ok"
        assert len(final_blueprints) == 1, "expected existing blueprint to be reused, not duplicated"
        assert final_blueprints[0].blueprint_id == meeting_blueprint_id
        assert reuse_messages, "expected workflow log to show the Meeting blueprint was reused"
        assert not phase_2_errors, "did not expect no-matching-blueprint error after creating Meeting blueprint"
        assert instances, "expected at least one instance to be stored through the reused blueprint"

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
