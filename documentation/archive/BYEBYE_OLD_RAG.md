# Remove the Old RAG Feature

Remove the bucket/blueprint retrieval workflow while keeping KnowledgeEngine and Milvus available as reusable embedding and vector database services. The code removal below is implemented. Existing database records, Redis keys, Milvus collections, and volumes have not been deleted.

## Keep

- `external_service/knowledge_engine.py` and `external_service/milvus_instance.py`, including embedding, collection, upsert, search, hybrid search, and delete capabilities.
- Their startup initialization, `KNOWLEDGE_ENGINE_URL`, `MILVUS_URI`, `pymilvus`, and `compose.milvus.yaml` with its backing services and volumes.
- Normal chat, operators, subagents, logging, PostgreSQL `session_message` and `openai_resource`, and Redis message caching.

## Removal Plan

1. **Separate reusable vector functionality first.** The old `knowledge_accessor.py` owns the explicit collection schema, BM25 function, and vector indexes. Preserve that capability outside the old knowledge module before deleting it. The generic `MilvusInstance.create_collection()` does not currently create the schema required by `hybrid_search()`, which expects `embedding` and `sparse_vector` and returns IDs under `kn_id`. Make this contract explicit and independent of bucket/blueprint tables. Keep a callable embedding/vector service interface; the current adapters alone are not standalone public HTTP endpoints.
2. **Remove the old backend workflow.** Delete `dynamic_agent_service/knowledge/` after extracting reusable collection setup. Remove `/knowledge/*` endpoints and request models, bucket/blueprint/instance monitor endpoints, the session RAG endpoint and response field, `RagCache`, RAG cache accessors, and obsolete `bucket_name` fields and trigger parameters.
3. **Remove the old SDK feature.** Delete `RagOperator` and its exports. Remove bucket management, retrieval, and node-expansion methods from the SDK, plus `bucket_name` in client trigger requests. Keep the general operator mechanism.
4. **Remove old schema definitions.** Remove `bucket`, `blueprint`, `blueprint_attribute`, `blueprint_instance`, and `instance_source` from `init_storage.py`. Existing data cleanup is a separate migration: after confirming ownership and retention, drop those tables in dependency order and remove only legacy RAG cache keys and collections. Do not delete Milvus volumes or collections still used by the vector service.
5. **Update tests and documentation.** Remove the old RAG smoke test and fixture, update the schema assertion that expects `bucket`, and remove obsolete SDK examples. Update `documentation/storage/tables.md` to retain the supported vector storage design while removing old knowledge tables and session RAG caching. Keep shared dependencies; regenerate the lockfile only if dependencies change.

## Verification After Removal

Use isolated test configuration, a disposable PostgreSQL database, a dedicated Redis test namespace, and uniquely named Milvus test collections. Do not modify running-service data.

| Check | Passing result |
| --- | --- |
| Remaining references | Search for `RagOperator`, `RagCache`, `/knowledge/`, `bucket_name`, and old knowledge-module imports. No active old-workflow references remain; retained vector schema compatibility and this plan are reviewed exceptions. |
| Imports and startup | SDK imports and service startup succeed. KnowledgeEngine, Milvus, PostgreSQL, and Redis initialize; `/health` succeeds. Health alone is not proof of vector functionality. |
| Embedding and vector round trip | Embed sample text, check vector dimension, create a temporary collection, upsert records, search and verify expected IDs, inspect the collection, delete records, then drop only the temporary collection. No bucket/blueprint rows are needed. |
| Hybrid search | Create a temporary collection with the retained dense/BM25 schema and indexes. Confirm dense and hybrid searches return the expected IDs and requested fields. |
| APIs and SDK | Removed routes are absent from OpenAPI and return 404. Removed SDK exports are absent. The retained vector service interface can be called independently of the old RAG feature. |
| Agent regression | Existing unit tests pass; basic chat streaming, operator calls, subagents, message persistence/cache reload, session cleanup, model selection, and logging still work. |
| Fresh database | Initialization creates `session_message` and `openai_resource`, with their constraints and indexes, and none of the five old knowledge tables. |
| Existing deployment | Rehearse any data migration on a disposable copy. Shared vector collections and retained message/resource data remain intact. |

Completion means the old RAG workflow is gone and embedding/vector operations work independently, with all temporary test resources cleaned up.

## Implementation and Verification Status

- Removed the old knowledge module, APIs, SDK operator/helpers, session RAG state, five table definitions, and obsolete tests/examples. Updated the Chinese storage documentation.
- Kept KnowledgeEngine, Milvus, their configuration/dependencies, and deployment services. Added `MilvusInstance.create_hybrid_collection(name, dimension)` for standalone text/vector storage. It creates `kn_id`, `value`, `embedding`, and generated `sparse_vector` fields with dense/BM25 indexes. The existing generic `create_collection()` remains available.
- The retained interface is Python: obtain vectors through `await KnowledgeEngine.get_embeddings(texts)`, create the hybrid collection, and upsert dictionaries containing `kn_id`, `value`, and `embedding`. Call `search(..., vector_field="embedding")` or `hybrid_search(...)`. No new public HTTP endpoints were added.
- Fixed hybrid result parsing for MilvusClient dictionary responses, standalone embedding initialization, and Milvus shutdown cleanup.
- The 12 focused unit checks pass. The full unit suite has two pre-existing issues, reproduced against committed HEAD: `test_log_accessor` imports a nonexistent module-level `clear_system_log`, and one `test_agent_runner` subagent event assertion fails.
- Live vector verification is not yet completed: dedicated test endpoints are not configured. Set `VECTOR_TEST_MILVUS_URI` and `VECTOR_TEST_KNOWLEDGE_ENGINE_URL` to isolated test services, then run `python -m unittest tests.integration.test_vector_services -v`. The test creates and removes only its uniquely named collection.
