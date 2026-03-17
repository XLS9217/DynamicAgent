"""
init class with values and execute directly
"""
import json
from dynamic_agent_service.agent.language_engine import LanguageEngine

SYSTEM_PROMPT = """You are a knowledge architect. Given a user query about what they want to know and raw knowledge text,
identify the necessary attributes to answer the query and extract their descriptions from the raw knowledge.

Output ONLY valid JSON in this format:
{"attribute_name": "attribute_description", ...}

Rules:
- Attribute names MUST be in English, lowercase, using underscores (e.g. product_features, target_users)
- Attribute descriptions MUST be in the same language as the raw knowledge text
- Only create attributes that are relevant to answering the user's query
- Extract descriptions directly from the raw knowledge, keeping them concise and informative"""


class CreateBPWorkflow:
    def __init__(self, language_engine: LanguageEngine, instruction: str, raw_knowledge: str):
        self.language_engine = language_engine
        self.instruction = instruction
        self.raw_knowledge = raw_knowledge

    def execute(self) -> dict[str, str]:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"User Query: {self.instruction}\n\nRaw Knowledge:\n{self.raw_knowledge}"},
        ]
        result = ""
        for chunk in self.language_engine.stream_response(messages):
            delta = chunk.choices[0].delta
            if delta.content:
                result += delta.content
        return json.loads(result)