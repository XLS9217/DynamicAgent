import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from pymilvus import MilvusClient

from dynamic_agent_service.external_service.knowledge_engine import KnowledgeEngine
from dynamic_agent_service.external_service.milvus_instance import MilvusInstance


class VectorServicesTest(unittest.TestCase):
    def test_hybrid_collection_supports_text_and_dense_search_without_relational_ids(self):
        client = MagicMock()
        client.has_collection.return_value = False
        client.create_schema.side_effect = MilvusClient.create_schema
        client.prepare_index_params.side_effect = MilvusClient.prepare_index_params
        with patch.object(MilvusInstance, "get_client", return_value=client):
            MilvusInstance.create_hybrid_collection("test_vectors", 3)
        creation = client.create_collection.call_args.kwargs
        schema = creation["schema"].to_dict()
        fields = {f["name"]: f for f in schema["fields"]}
        self.assertEqual(set(fields), {"kn_id", "value", "embedding", "sparse_vector"})
        self.assertTrue(fields["kn_id"]["is_primary"])
        self.assertEqual(fields["embedding"]["params"]["dim"], 3)
        self.assertEqual(schema["functions"][0]["input_field_names"], ["value"])
        self.assertEqual(schema["functions"][0]["output_field_names"], ["sparse_vector"])
        client.load_collection.assert_called_once_with("test_vectors")

    def test_existing_collection_is_not_overwritten(self):
        client = MagicMock()
        client.has_collection.return_value = True
        with patch.object(MilvusInstance, "get_client", return_value=client):
            self.assertEqual(MilvusInstance.create_hybrid_collection("existing", 3), "existing")
        client.create_collection.assert_not_called()

    def test_hybrid_search_reads_milvus_client_dictionary_results(self):
        client = MagicMock()
        client.hybrid_search.return_value = [[
            {"id": "record-1", "distance": 0.9, "entity": {"value": "sample text"}},
        ]]
        with patch.object(MilvusInstance, "get_client", return_value=client):
            result = MilvusInstance.hybrid_search(
                "test_vectors", [1.0, 0.0, 0.0], "sample", output_fields=["value"],
            )
        self.assertEqual(result, [{"kn_id": "record-1", "distance": 0.9, "value": "sample text"}])

    def test_dense_search_selects_field_in_multi_vector_collection(self):
        client = MagicMock()
        client.search.return_value = [[]]
        with patch.object(MilvusInstance, "get_client", return_value=client):
            self.assertEqual(MilvusInstance.search("test_vectors", [1.0], vector_field="embedding"), [])
        self.assertEqual(client.search.call_args.kwargs["anns_field"], "embedding")
        self.assertEqual(client.search.call_args.kwargs["filter"], "")


class KnowledgeEngineTest(unittest.IsolatedAsyncioTestCase):
    async def test_embeddings_work_without_explicit_startup(self):
        response = MagicMock()
        response.json.return_value = {"embeddings": [{"embedding": [1.0, 0.0]}]}
        client = MagicMock()
        client.post = AsyncMock(return_value=response)
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=client)
        context.__aexit__ = AsyncMock(return_value=None)
        with (
            patch.object(KnowledgeEngine, "_base_url", None),
            patch.object(KnowledgeEngine, "_dimension", None),
            patch.dict(os.environ, {"KNOWLEDGE_ENGINE_URL": "http://embedding.test"}),
            patch("dynamic_agent_service.external_service.knowledge_engine.httpx.AsyncClient", return_value=context),
        ):
            self.assertEqual(await KnowledgeEngine.get_embeddings(["sample"]), [[1.0, 0.0]])
            self.assertEqual(KnowledgeEngine.get_dimension(), 2)
        client.post.assert_awaited_once_with(
            "http://embedding.test/embeddings", json={"text_list": ["sample"]}, timeout=60,
        )
