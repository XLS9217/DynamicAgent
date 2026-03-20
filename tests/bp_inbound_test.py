import os
import sys
import json
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from dynamic_agent_service.external_service.pg_instance import PgInstance
from dynamic_agent_service.knowledge.blueprint_accessor import BlueprintAccessor
from tests.dump_knowledge import dump_to_cache
from workflow.knowledge_inbound_workflow import KnowledgeInboundWorkflow
from workflow.workflow_base import build_workflow

load_dotenv()

PDF_PATH = os.getenv("TEST_PDF_PATH")
CACHE_DIR = os.getenv("CACHE_DIR")

query_list = [
    "",
    "I want to know the product features, target users, usage scenarios, technical architecture, and competitive advantages about the product",
    "请给它建立一个完整的描述",
    "我想全面了解这个产品，包括它的产品功能、目标用户、使用场景、技术架构，以及相对竞品的核心优势。",
    "Please summarize this product.",
]

query = "记录这个产品，包括它的名字，产品功能、目标用户、使用场景、技术架构，以及相对竞品的核心优势。"


async def run_single_test(index: int, query: str, knowledge_accessor=None):
    test_cache_dir = os.path.join(CACHE_DIR, f"test_{index}")
    os.makedirs(test_cache_dir, exist_ok=True)

    inbound_wf = await build_workflow(
        KnowledgeInboundWorkflow,
        PDF_PATH,
        "pdf",
        query,
        knowledge_accessor=knowledge_accessor,
        workflow_bucket=os.path.join(test_cache_dir, "KnowledgeInboundWorkflow.jsonl")
    )
    await inbound_wf.execute()

    with open(os.path.join(test_cache_dir, "merged.md"), "w", encoding="utf-8") as f:
        f.write(inbound_wf._raw_knowledge_text)

    with open(os.path.join(test_cache_dir, "schema.md"), "w", encoding="utf-8") as f:
        f.write(f"# Blueprint: {inbound_wf._blueprint_schema.description}\n\n**Query:** {query}\n\n")
        for attr_name, attr_schema in inbound_wf._blueprint_schema.attributes.items():
            f.write(f"### {attr_name}\n\n{attr_schema.description}\n\n")

    with open(os.path.join(test_cache_dir, "filled.md"), "w", encoding="utf-8") as f:
        f.write(f"# Blueprint: {inbound_wf._blueprint_schema.description}\n\n**Query:** {query}\n\n")
        for attr_name, attr_value in inbound_wf._filled_blueprint.items():
            f.write(f"### {attr_name}\n\n{attr_value}\n\n")

    print(f"[test_{index}] Blueprint: {inbound_wf._blueprint_schema.description}")
    print(f"[test_{index}] Generated {len(inbound_wf._blueprint_schema.attributes)} attributes")
    print(f"[test_{index}] {json.dumps(inbound_wf._filled_blueprint, ensure_ascii=False, indent=2)}")


async def main():
    os.makedirs(CACHE_DIR, exist_ok=True)

    await PgInstance.initialize()
    await BlueprintAccessor.ensure_tables_exist()

    # Single query test
    await run_single_test(0, query, knowledge_accessor=BlueprintAccessor)

    # Batch test (comment/uncomment to switch)
    # await asyncio.gather(*(run_single_test(i, q, knowledge_accessor=BlueprintAccessor) for i, q in enumerate(query_list)))

    await dump_to_cache(CACHE_DIR)
    await PgInstance.close()


if __name__ == "__main__":
    asyncio.run(main())