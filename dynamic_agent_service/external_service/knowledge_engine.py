import os
import httpx


class KnowledgeEngine:
    _base_url: str | None = None
    _dimension: int | None = None

    @classmethod
    def initialize(cls):
        cls._base_url = os.getenv("KNOWLEDGE_ENGINE_URL")

    @classmethod
    def get_dimension(cls) -> int:
        return cls._dimension

    @classmethod
    async def get_embeddings(cls, text_list: list[str]) -> list[list[float]]:
        if cls._base_url is None:
            cls.initialize()
        async with httpx.AsyncClient(mounts={"http://": None}) as client:
            resp = await client.post(
                f"{cls._base_url}/embeddings",
                json={"text_list": text_list},
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            embeddings = [item["embedding"] for item in data["embeddings"]]
            if embeddings and cls._dimension is None:
                cls._dimension = len(embeddings[0])
            return embeddings