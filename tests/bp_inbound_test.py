import os
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from dynamic_agent_service.external_service.pg_instance import PgInstance
from dynamic_agent_service.external_service.knowledge_engine import KnowledgeEngine
from dynamic_agent_service.knowledge.blueprint_accessor import BlueprintAccessor
from dynamic_agent_service.knowledge.knowledge_node_accessor import KnowledgeNodeAccessor
from tests.dump_knowledge import dump_to_cache
from workflow.inbound.knowledge_inbound_workflow import KnowledgeInboundWorkflow
from workflow.workflow_base import build_workflow

load_dotenv()

PDF_PATH = os.getenv("TEST_PDF_PATH")
CACHE_DIR = os.getenv("CACHE_DIR")

query = "记录这个产品，包括它的名字，产品功能、目标用户、使用场景、技术架构，以及相对竞品的核心优势。"


async def run_single_test(index: int, file_path: str, query: str, knowledge_accessor=None):
    log_dir = os.path.join(CACHE_DIR, f"file_{index}")
    os.makedirs(log_dir, exist_ok=True)

    inbound_wf = await build_workflow(
        KnowledgeInboundWorkflow,
        file_path,
        "pdf",
        query,
        knowledge_accessor=knowledge_accessor,
        workflow_bucket=os.path.join(log_dir, "KnowledgeInboundWorkflow.jsonl")
    )
    await inbound_wf.execute()

    print(f"  File: {Path(file_path).name}")
    print(f"  Blueprint: {inbound_wf._blueprint_schema.name}")
    print(f"  Attributes: {len(inbound_wf._blueprint_schema.attributes)}")
    print(f"  Filled: {len(inbound_wf._filled_blueprint)}")


async def main():
    os.makedirs(CACHE_DIR, exist_ok=True)

    await PgInstance.initialize()
    await BlueprintAccessor.ensure_tables_exist()

    # Warm up embedding dimension before creating Milvus collection
    await KnowledgeEngine.get_embeddings(["init"])
    await KnowledgeNodeAccessor.ensure_tables_exist()

    file_index = 0
    for subfolder in sorted(Path(PDF_PATH).iterdir()):
        if not subfolder.is_dir():
            continue
        pdf_files = sorted(subfolder.glob("*.pdf"))
        if not pdf_files:
            continue
        print(f"\n=== {subfolder.name} ({len(pdf_files)} PDFs) ===")
        for pdf_file in pdf_files:
            print(f"\n--- [{file_index}] {pdf_file.name} ---")
            await run_single_test(file_index, str(pdf_file), query, knowledge_accessor=BlueprintAccessor)
            file_index += 1

    await dump_to_cache(CACHE_DIR)
    await PgInstance.close()


if __name__ == "__main__":
    asyncio.run(main())