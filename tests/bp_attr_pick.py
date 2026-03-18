import os
import sys
import json
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from dynamic_agent_service.agent.language_engine import LanguageEngine
from dynamic_agent_service.agent.vision_engine import VisionEngine
from dynamic_agent_service.knowledge.file_textification_workflow import FileTextificationWorkflow
from dynamic_agent_service.knowledge.blueprint_generation_workflow import BlueprintGenerationWorkflow

load_dotenv()

PDF_PATH = os.getenv("TEST_PDF_PATH")
CACHE_DIR = os.getenv("CHCHE_DIR")


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

    # Extract text from file (parallel)
    raw_knowledge = await FileTextificationWorkflow(vision_engine, PDF_PATH, "pdf").execute()
    print(f"Extracted {len(raw_knowledge)} characters")

    # Save merged text
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(os.path.join(CACHE_DIR, "airlink_merged.md"), "w", encoding="utf-8") as f:
        f.write(raw_knowledge)

    # Step 1: Generate blueprint schema
    query = "I want to know the product features, target users, usage scenarios, technical architecture, and competitive advantages about AirLink"
    blueprint = await BlueprintGenerationWorkflow(llm_engine, query).execute()
    print(f"Blueprint: {blueprint.description}")
    print(f"Generated {len(blueprint.attributes)} attributes")

    # Save schema
    with open(os.path.join(CACHE_DIR, "airlink_attribute_schema.md"), "w", encoding="utf-8") as f:
        f.write(f"# Blueprint: {blueprint.description}\n\n**Query:** {query}\n\n")
        for attr_name, attr_desc in blueprint.attributes.items():
            f.write(f"### {attr_name}\n\n{attr_desc}\n\n")

    # Step 2: Fill attribute values
    fill_prompt = f"""Given the attribute schema and raw knowledge, extract the actual values for each attribute.

Attribute Schema:
{json.dumps(blueprint.attributes, ensure_ascii=False, indent=2)}

Raw Knowledge:
{raw_knowledge}

Output ONLY valid JSON: {{"attribute_name": "actual value from raw knowledge", ...}}
Values MUST be in the same language as the raw knowledge."""

    fill_result = await llm_engine.async_get_response([{"role": "user", "content": fill_prompt}])
    attribute_values = json.loads(fill_result)
    print(json.dumps(attribute_values, ensure_ascii=False, indent=2))

    # Save final attributes
    with open(os.path.join(CACHE_DIR, "airlink_attributes.md"), "w", encoding="utf-8") as f:
        f.write(f"# Blueprint: {blueprint.description}\n\n**Query:** {query}\n\n")
        for attr_name, attr_value in attribute_values.items():
            f.write(f"### {attr_name}\n\n{attr_value}\n\n")


if __name__ == "__main__":
    asyncio.run(main())