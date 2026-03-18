import os
import sys
import json
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from dynamic_agent_service.agent.language_engine import LanguageEngine
from dynamic_agent_service.agent.vision_engine import VisionEngine
from dynamic_agent_service.util.file_process import pdf_to_images
from dynamic_agent_service.workflow.knowledge_extraction_workflow import KnowledgeExtractionWorkflow

load_dotenv()

PDF_PATH = r"E:\Project\_DynamicAgent\data\Products\AirLink\AirLink隔空投屏产品介绍 v1.9.pdf"
CACHE_DIR = os.getenv("CHCHE_DIR", r"E:\Project\_DynamicAgent\cache")


async def get_attr_desc(llm_engine: LanguageEngine, query: str) -> tuple[str, dict[str, str]]:
    """
    Step 1: Generate attribute schema from user query
    Returns: (blueprint_description, {attribute_name -> description of what the attribute represents})
    """
    schema_prompt = f"""Based on this user query, generate a reusable blueprint schema:

User Query: {query}

Output ONLY valid JSON in this format:
{{
  "blueprint_description": "A general description of what category/type this blueprint represents, applicable to any instance of this type",
  "attributes": {{
    "attribute_name": "description of what this attribute represents",
    ...
  }}
}}

Rules:
- Blueprint description must be general and reusable, not specific to any particular instance
- Attribute names must be in English, lowercase, using underscores
- Keep descriptions concise"""

    schema_result = await llm_engine.async_get_response([{"role": "user", "content": schema_prompt}])
    result = json.loads(schema_result)
    return (result["blueprint_description"], result["attributes"])


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

    # Convert PDF to images
    images = pdf_to_images(PDF_PATH)
    print(f"Converted {len(images)} pages")

    # Extract text from images (parallel)
    raw_knowledge = await KnowledgeExtractionWorkflow(vision_engine, images).execute()
    print(f"Extracted {len(raw_knowledge)} characters")

    # Save merged text
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(os.path.join(CACHE_DIR, "airlink_merged.md"), "w", encoding="utf-8") as f:
        f.write(raw_knowledge)

    # Step 1: Generate attribute schema
    query = "I want to know the product features, target users, usage scenarios, technical architecture, and competitive advantages about AirLink"
    blueprint_desc, attribute_schema = await get_attr_desc(llm_engine, query)
    print(f"Blueprint: {blueprint_desc}")
    print(f"Generated {len(attribute_schema)} attributes")

    # Save schema
    with open(os.path.join(CACHE_DIR, "airlink_attribute_schema.md"), "w", encoding="utf-8") as f:
        f.write(f"# Blueprint: {blueprint_desc}\n\n**Query:** {query}\n\n")
        for attr_name, attr_desc in attribute_schema.items():
            f.write(f"### {attr_name}\n\n{attr_desc}\n\n")

    # Step 2: Fill attribute values
    fill_prompt = f"""Given the attribute schema and raw knowledge, extract the actual values for each attribute.

Attribute Schema:
{json.dumps(attribute_schema, ensure_ascii=False, indent=2)}

Raw Knowledge:
{raw_knowledge}

Output ONLY valid JSON: {{"attribute_name": "actual value from raw knowledge", ...}}
Values MUST be in the same language as the raw knowledge."""

    fill_result = await llm_engine.async_get_response([{"role": "user", "content": fill_prompt}])
    attribute_values = json.loads(fill_result)
    print(json.dumps(attribute_values, ensure_ascii=False, indent=2))

    # Save final attributes
    with open(os.path.join(CACHE_DIR, "airlink_attributes.md"), "w", encoding="utf-8") as f:
        f.write(f"# Blueprint: {blueprint_desc}\n\n**Query:** {query}\n\n")
        for attr_name, attr_value in attribute_values.items():
            f.write(f"### {attr_name}\n\n{attr_value}\n\n")


if __name__ == "__main__":
    asyncio.run(main())