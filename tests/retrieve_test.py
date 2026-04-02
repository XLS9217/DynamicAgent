import os
import sys
import asyncio
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from dynamic_agent_service.external_service.pg_instance import PgInstance
from dynamic_agent_service.knowledge.blueprint_accessor import BlueprintAccessor
from workflow.retrieve.knowledge_retrieve_workflow import KnowledgeRetrieveWorkflow
from workflow.workflow_base import build_workflow

load_dotenv()

CACHE_DIR = os.getenv("CACHE_DIR", "E:\\Project\\_DynamicAgent\\cache")
BUCKET_NAME = "test"

# Test queries - natural user questions
TEST_QUERIES = [
    {
        "name": "semantic_query",
        "query": "我想找一个可以在会议室里无线投屏的产品",  # "I want to find a product for wireless screen casting in meeting rooms"
        "description": "Semantic query - conceptual need"
    },
    {
        "name": "keyword_query",
        "query": "AirLink怎么用PIN码投屏",  # "How to use AirLink with PIN code for screen casting"
        "description": "Keyword query - specific product and feature"
    },
    {
        "name": "mixed_query",
        "query": "访客系统支持哪些登记方式",  # "What registration methods does the visitor system support"
        "description": "Mixed query - specific system with general question"
    }
]


async def run_query_test(query_config: dict, bucket_cache: Path):
    """Run retrieve test for a single query."""
    query = query_config["query"]
    query_name = query_config["name"]

    # Create query-specific folder
    query_cache = bucket_cache / query_name
    query_cache.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"Query: {query}")
    print(f"Type: {query_config['description']}")
    print(f"{'='*60}")

    # Use KnowledgeRetrieveWorkflow
    top_k = 10
    print(f"\nRunning retrieve workflow with top_k={top_k}...")

    retrieve_wf = await build_workflow(
        KnowledgeRetrieveWorkflow,
        query,
        BUCKET_NAME,
        top_k,
        knowledge_accessor=BlueprintAccessor,
        workflow_bucket=query_cache / "retrieve_workflow.jsonl"
    )

    reconstructed = await retrieve_wf.execute()

    print(f"Reconstructed {len(reconstructed)} instances")

    # Dump results to cache
    output = {
        "query": query,
        "query_type": query_name,
        "description": query_config["description"],
        "bucket_name": BUCKET_NAME,
        "top_k": top_k,
        "reconstructed_instances": reconstructed
    }

    output_path = query_cache / "retrieve_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nDumped results to {output_path}")
    print("\nReconstructed instances:")
    for i, inst in enumerate(reconstructed[:3]):
        print(f"\n[{i}] Attributes: {list(inst.keys())}")
        # Show first attribute value preview
        first_attr = list(inst.keys())[0] if inst else None
        if first_attr:
            value = inst[first_attr]
            preview = value[:80] + "..." if len(value) > 80 else value
            print(f"    {first_attr}: {preview}")


async def main():
    bucket_cache = Path(CACHE_DIR) / BUCKET_NAME
    bucket_cache.mkdir(parents=True, exist_ok=True)

    await PgInstance.initialize()

    # Run all test queries
    for query_config in TEST_QUERIES:
        await run_query_test(query_config, bucket_cache)

    await PgInstance.close()
    print("\n" + "="*60)
    print("All queries completed!")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())