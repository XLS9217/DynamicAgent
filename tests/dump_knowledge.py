import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from dynamic_agent_service.external_service.pg_instance import PgInstance
from dynamic_agent_service.knowledge.blueprint_accessor import BlueprintAccessor


async def dump_to_cache(cache_dir: str):
    blueprints = await BlueprintAccessor.get_blueprint_list()
    result = [bp.model_dump() for bp in blueprints]

    out_path = Path(cache_dir) / "knowledge_dump.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"Dumped {len(result)} blueprints to {out_path}")


async def main():
    load_dotenv()
    await PgInstance.initialize()

    cache_dir = os.getenv("CACHE_DIR", ".")
    os.makedirs(cache_dir, exist_ok=True)
    await dump_to_cache(cache_dir)

    await PgInstance.close()


if __name__ == "__main__":
    asyncio.run(main())
