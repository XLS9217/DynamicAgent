import os
import sys
import json
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from workflow.knowledge_inbound_workflow import KnowledgeInboundWorkflow
from workflow.workflow_base import build_workflow

load_dotenv()

PDF_PATH = os.getenv("TEST_PDF_PATH")
CACHE_DIR = os.getenv("CACHE_DIR") or str(Path(__file__).parent / "cache")


async def main():
    query = "I want to know the product features, target users, usage scenarios, technical architecture, and competitive advantages about AirLink"
    inbound_wf = await build_workflow(
        KnowledgeInboundWorkflow,
        PDF_PATH,
        "pdf",
        query
    )
    await inbound_wf.execute()

    os.makedirs(CACHE_DIR, exist_ok=True)

    with open(os.path.join(CACHE_DIR, "merged.md"), "w", encoding="utf-8") as f:
        f.write(inbound_wf._raw_knowledge_text)

    with open(os.path.join(CACHE_DIR, "schema.md"), "w", encoding="utf-8") as f:
        f.write(f"# Blueprint: {inbound_wf._blueprint_schema.description}\n\n**Query:** {query}\n\n")
        for attr_name, attr_desc in inbound_wf._blueprint_schema.attributes.items():
            f.write(f"### {attr_name}\n\n{attr_desc}\n\n")

    with open(os.path.join(CACHE_DIR, "filled.md"), "w", encoding="utf-8") as f:
        f.write(f"# Blueprint: {inbound_wf._blueprint_schema.description}\n\n**Query:** {query}\n\n")
        for attr_name, attr_value in inbound_wf._filled_blueprint.items():
            f.write(f"### {attr_name}\n\n{attr_value}\n\n")

    print(f"Blueprint: {inbound_wf._blueprint_schema.description}")
    print(f"Generated {len(inbound_wf._blueprint_schema.attributes)} attributes")
    print(json.dumps(inbound_wf._filled_blueprint, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
