import os
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from dynamic_agent_service.external_service.pg_instance import PgInstance
from dynamic_agent_service.external_service.knowledge_engine import KnowledgeEngine
from dynamic_agent_service.knowledge.knowledge_accessor import KnowledgeAccessor
from dynamic_agent_service.knowledge.blueprint_accessor import BlueprintAccessor
from dynamic_agent_service.knowledge.knowledge_node_accessor import KnowledgeNodeAccessor
from dynamic_agent_service.knowledge.knowledge_structs import Bucket
from dynamic_agent_service.knowledge.knowledge_interface import KnowledgeInterface
from workflow.utility.file_textification_workflow import FileTextificationWorkflow
from workflow.workflow_base import build_workflow

load_dotenv()


async def main():
    if len(sys.argv) < 5:
        print("Usage: python inbound_knowledge.py <bucket_name> <pdf_path> <cache_folder> <inbound_query>")
        sys.exit(1)

    bucket_name = sys.argv[1]
    pdf_path = sys.argv[2]
    cache_folder = sys.argv[3]
    inbound_query = sys.argv[4]

    bucket_cache = Path(cache_folder) / bucket_name
    bucket_cache.mkdir(parents=True, exist_ok=True)

    await PgInstance.initialize()

    # Ensure bucket exists
    existing_bucket = await KnowledgeAccessor.get_bucket(bucket_name)
    if not existing_bucket:
        bucket = Bucket(name=bucket_name, description=f"Bucket: {bucket_name}")
        await KnowledgeAccessor.create_bucket(bucket)
        print(f"Created bucket: {bucket_name}")
    else:
        print(f"Using existing bucket: {bucket_name}")

    # Textify file
    print(f"Processing: {pdf_path}")
    textify_wf = await build_workflow(
        FileTextificationWorkflow,
        pdf_path,
        "pdf",
        workflow_bucket=bucket_cache / "textification.jsonl"
    )
    knowledge_text = await textify_wf.execute()
    print(f"Extracted {len(knowledge_text)} characters")

    # Inbound
    result = await KnowledgeInterface.inbound(inbound_query, knowledge_text, bucket_name)

    print(f"Blueprint: {result['blueprint']['name']}")
    print(f"Attributes: {len(result['blueprint']['attributes'])}")
    print(f"Filled: {len(result['attribute_values'])}")

    await PgInstance.close()
    print("Done")


if __name__ == "__main__":
    asyncio.run(main())