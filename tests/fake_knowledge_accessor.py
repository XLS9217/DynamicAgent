import json
import os
import uuid
from pathlib import Path

from dynamic_agent_service.knowledge.knowledge_structs import Blueprint


class FakeKnowledgeAccessor:

    def __init__(self, cache_dir: str):
        self._db_path = Path(cache_dir) / "fake_db.json"
        self._data: dict[str, dict] = {}
        if self._db_path.exists():
            with open(self._db_path, "r", encoding="utf-8") as f:
                self._data = json.load(f)

    def _save(self):
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._db_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def create_blueprint(self, blueprint: Blueprint) -> str:
        blueprint_id = str(uuid.uuid4())
        self._data[blueprint_id] = blueprint.model_dump()
        self._save()
        return blueprint_id

    def get_blueprint(self, blueprint_id: str) -> Blueprint | None:
        entry = self._data.get(blueprint_id)
        if entry is None:
            return None
        return Blueprint(**entry)

    def get_blueprint_list(self) -> list[Blueprint]:
        return [Blueprint(**v) for v in self._data.values()]


SEED_PROMPT = """Generate 6 diverse blueprint schemas for a knowledge management system.
Each blueprint should represent a different category of knowledge (e.g. product, person, company, event, research_paper, recipe).

Output ONLY valid JSON as a list:
[
  {{"name": "snake_case_name", "description": "general reusable description", "attributes": {{"attr_name": "attr description", ...}}}},
  ...
]"""


async def main():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from dotenv import load_dotenv
    from dynamic_agent_service.agent.language_engine import LanguageEngine

    load_dotenv()
    cache_dir = os.getenv("CACHE_DIR", ".")
    os.makedirs(cache_dir, exist_ok=True)

    engine = LanguageEngine(
        api_key=os.getenv("LLM_API_KEY"),
        base_url=os.getenv("LLM_BASE_URL"),
        model=os.getenv("LLM_NAME")
    )
    raw = await engine.async_get_response([{"role": "user", "content": SEED_PROMPT}])
    blueprints = json.loads(raw)

    accessor = FakeKnowledgeAccessor(cache_dir)
    for bp_data in blueprints:
        bp = Blueprint(**bp_data)
        bp_id = accessor.create_blueprint(bp)
        print(f"Created: {bp.name} ({len(bp.attributes)} attrs) -> {bp_id}")

    print(f"\nSaved {len(blueprints)} blueprints to {accessor._db_path}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())