"""Smoke test retrieval from a directly seeded synthetic knowledge bucket."""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv

from dynamic_agent_client import (
    AgentEvent,
    DynamicAgentClient,
    RagOperator,
    ToolExecutionEvent,
)
from dynamic_agent_client.service_handler import ServiceHandler
from dynamic_agent_service.external_service.knowledge_engine import KnowledgeEngine
from dynamic_agent_service.external_service.milvus_instance import MilvusInstance
from dynamic_agent_service.external_service.pg_instance import PgInstance
from dynamic_agent_service.knowledge.knowledge_accessor import KnowledgeAccessor
from dynamic_agent_service.knowledge.knowledge_structs import (
    Blueprint,
    BlueprintAttributeSchema,
    Bucket,
)


load_dotenv()


SESSION_ID = "smoke-rag-retrieve"
BUCKET_NAME = "smoke-rag-retrieve"
FIXTURE_PATH = Path(__file__).parent.parent / "resource" / "rag_retrieve_fixture.json"
QUESTION = (
    "What does Sentinel Harbor detect, and what does it do with compromised endpoints?"
)


async def seed_knowledge() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    await KnowledgeAccessor.create_bucket(
        Bucket(
            name=BUCKET_NAME,
            description="Temporary synthetic data for the retrieval smoke test",
        )
    )

    blueprint_fixture = fixture["blueprint"]
    blueprint_id = await KnowledgeAccessor.create_blueprint(
        Blueprint(
            bucket_name=BUCKET_NAME,
            name=blueprint_fixture["name"],
            description=blueprint_fixture["description"],
            attributes={
                name: BlueprintAttributeSchema(**schema)
                for name, schema in blueprint_fixture["attributes"].items()
            },
        )
    )
    attributes = {
        attribute.name: attribute
        for attribute in await KnowledgeAccessor.get_attributes(blueprint_id)
    }

    pending_nodes = []
    for instance in fixture["instances"]:
        instance_id = instance["instance_id"]
        await KnowledgeAccessor.create_instance(instance_id, blueprint_id)
        await KnowledgeAccessor.create_instance_source(
            instance_id,
            instance["source_metadata"],
        )
        for attribute_name, value in instance["values"].items():
            pending_nodes.append(
                {
                    "kn_id": f"{instance_id}-{attribute_name}",
                    "instance_id": instance_id,
                    "attribute_id": attributes[attribute_name].attribute_id,
                    "value": value,
                }
            )

    embeddings = await KnowledgeEngine.get_embeddings(
        [node["value"] for node in pending_nodes]
    )
    for node, embedding in zip(pending_nodes, embeddings, strict=True):
        node["embedding"] = embedding
    KnowledgeAccessor.upsert_entities(BUCKET_NAME, pending_nodes)


async def main() -> None:
    client = None
    client_connected = False
    storage_initialized = False
    tool_calls = []
    tool_results = []

    try:
        await PgInstance.initialize()
        MilvusInstance.initialize()
        await KnowledgeEngine.initialize()
        storage_initialized = True

        if await KnowledgeAccessor.get_bucket(BUCKET_NAME) is not None:
            await KnowledgeAccessor.delete_bucket(BUCKET_NAME)
        await seed_knowledge()

        port = os.getenv("PORT", "7777")
        await DynamicAgentClient.connect(server_addr=f"http://localhost:{port}")
        client_connected = True
        await DynamicAgentClient.delete_session(SESSION_ID)

        client = await DynamicAgentClient.create(
            setting=(
                "Answer from the configured knowledge bucket. Always call the RAG "
                "retrieve tool before answering knowledge questions."
            ),
            session_id=SESSION_ID,
            persist=False,
        )
        assert client.messages == [], "fresh RAG smoke session should start empty"

        def on_event(event: AgentEvent) -> None:
            if not isinstance(event, ToolExecutionEvent):
                return
            if event.status == "started":
                tool_calls.append((event.name, event.arguments))
            elif event.status == "succeeded":
                tool_results.append((event.name, event.arguments, event.result))

        registration = await client.add_operator(
            RagOperator(bucket_name=BUCKET_NAME, top_k=5)
        )
        print(f"operator registered: {registration}")

        response = await client.trigger(QUESTION, on_event=on_event)

        assert tool_calls, "expected the RAG retrieve tool to be called"
        assert tool_calls[0][0] == "RagOperator_retrieve"
        assert tool_results, "expected a RAG tool result"
        assert tool_results[0][0] == "RagOperator_retrieve"
        assert tool_results[0][2], "expected non-empty retrieved knowledge"
        assert "Sentinel Harbor" in str(tool_results[0][2])
        assert "isolates compromised endpoints" in str(tool_results[0][2])
        assert response.strip(), "expected a non-empty grounded response"

        print(f"tool: {tool_calls[0][0]}")
        print(f"retrieval result items: {len(tool_results[0][2])}")
        print(f"response: {response}")
        print("ALL PASSED")
    finally:
        if client is not None:
            await client.close()
        if client_connected:
            await DynamicAgentClient.delete_session(SESSION_ID)
        await ServiceHandler.stop()
        if storage_initialized:
            try:
                if await KnowledgeAccessor.get_bucket(BUCKET_NAME) is not None:
                    await KnowledgeAccessor.delete_bucket(BUCKET_NAME)
            finally:
                MilvusInstance.close()
                await PgInstance.close()


if __name__ == "__main__":
    asyncio.run(main())
