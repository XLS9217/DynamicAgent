"""Opt-in vector round trip against dedicated test services, never the running app.

Set VECTOR_TEST_MILVUS_URI and VECTOR_TEST_KNOWLEDGE_ENGINE_URL to test endpoints.
Only the uniquely named collection created by this test is removed.
"""
import os
import unittest
import uuid
from unittest.mock import patch

from pymilvus import MilvusClient

from dynamic_agent_service.external_service.knowledge_engine import KnowledgeEngine
from dynamic_agent_service.external_service.milvus_instance import MilvusInstance


@unittest.skipUnless(
    os.getenv("VECTOR_TEST_MILVUS_URI") and os.getenv("VECTOR_TEST_KNOWLEDGE_ENGINE_URL"),
    "Dedicated vector test endpoints are not configured",
)
class VectorRoundTripTest(unittest.IsolatedAsyncioTestCase):
    async def test_embedding_dense_and_hybrid_round_trip(self):
        name = "test_vector_" + uuid.uuid4().hex
        client = MilvusClient(uri=os.environ["VECTOR_TEST_MILVUS_URI"], timeout=15)
        try:
            with (
                patch.object(MilvusInstance, "_client", client),
                patch.object(KnowledgeEngine, "_base_url", os.environ["VECTOR_TEST_KNOWLEDGE_ENGINE_URL"]),
                patch.object(KnowledgeEngine, "_dimension", None),
            ):
                texts = ["orbital telescope astronomy", "fresh bread baking recipe"]
                vectors = await KnowledgeEngine.get_embeddings(texts)
                self.assertEqual(len(vectors), 2)
                dimension = KnowledgeEngine.get_dimension()
                self.assertGreater(dimension, 0)
                self.assertTrue(all(len(v) == dimension for v in vectors))
                MilvusInstance.create_hybrid_collection(name, dimension)
                MilvusInstance.upsert(name, [
                    {"kn_id": str(i), "value": text, "embedding": vector}
                    for i, (text, vector) in enumerate(zip(texts, vectors))
                ])
                client.flush(name)
                dense = MilvusInstance.search(name, vectors[0], top_k=1, vector_field="embedding")
                self.assertEqual(dense[0]["id"], "0")
                hybrid = MilvusInstance.hybrid_search(name, vectors[0], texts[0], top_k=1, output_fields=["value"])
                self.assertEqual(hybrid[0]["kn_id"], "0")
                self.assertEqual(hybrid[0]["value"], texts[0])
                self.assertEqual(MilvusInstance.get_collection_info(name)["collection_name"], name)
                MilvusInstance.delete(name, ["0", "1"])
                self.assertEqual(client.get(name, ids=["0", "1"], consistency_level="Strong"), [])
        finally:
            try:
                if client.has_collection(name):
                    client.drop_collection(name)
            finally:
                client.close()
