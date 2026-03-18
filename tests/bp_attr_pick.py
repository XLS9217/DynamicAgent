import os
import sys
import json
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from dynamic_agent_service.agent.language_engine import LanguageEngine
from dynamic_agent_service.agent.vision_engine import VisionEngine
from workflow.knowledge_inbound_workflow import KnowledgeInboundWorkflow

load_dotenv()

PDF_PATH = os.getenv("TEST_PDF_PATH")
CACHE_DIR = os.getenv("CACHE_DIR") or str(Path(__file__).parent / "cache")


async def main():
    llm_engine = LanguageEngine(
        api_key=os.getenv("LLM_API_KEY"),
        base_url=os.getenv("LLM_BASE_URL"),
        model=os.getenv("LLM_NAME")
    )
    vision_engine = VisionEngine(
        api_key=os.getenv("VLM_API_KEY"),
        base_url=os.getenv("VLM_BASE_URL"),
        model=os.getenv("VLM_NAME")
    )

    query = "I want to know the product features, target users, usage scenarios, technical architecture, and competitive advantages about AirLink"
    inbound_wf = KnowledgeInboundWorkflow(
        llm_engine,
        vision_engine,
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

    inbound_wf.save_jsonl(os.path.join(CACHE_DIR, "knowledge_inbound_log.jsonl"))

    print(f"Blueprint: {inbound_wf._blueprint_schema.description}")
    print(f"Generated {len(inbound_wf._blueprint_schema.attributes)} attributes")
    print(json.dumps(inbound_wf._filled_blueprint, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
