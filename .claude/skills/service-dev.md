---
name: service-dev
description: Comprehensive guidelines for developing the DynamicAgent service, including SDK development and RAG system development
---

# Service Development Guideline

You are helping develop the DynamicAgent service, which includes:
1. The core FastAPI service (`dynamic_agent_service/`)
2. Client SDKs (`packages/dynamic_agent_client/`)
3. RAG knowledge system (`workflow/`, `dynamic_agent_service/knowledge/`)

Follow these guidelines strictly.

---

## Part 1: SDK Development

### Core Concepts

Every SDK must expose these abstractions:

1. **Client** — connects to the service, manages sessions, sends/receives messages
2. **Operator** — a user-defined tool provider that groups related tools
3. **Tool** — a single callable function exposed to the agent, declared via decorator/attribute/macro depending on language
4. **Session** — a stateful conversation context created through the client

### Communication Contract

- The service exposes HTTP + WebSocket endpoints
- SDK connects via HTTP for session lifecycle (create, close)
- SDK connects via WebSocket for streaming (agent responses, tool invocations)
- Tool execution is callback-based: service calls back into the SDK when a tool is invoked
- The SDK runs a local webhook server to receive tool invocation requests

### SDK Must Implement

| Capability              | Description                                                  |
|-------------------------|--------------------------------------------------------------|
| `connect(addr)`        | Establish connection to the service                          |
| `create(setting, ...)`  | Create a new session with agent configuration                |
| `trigger(text, ...)`    | Send user message and stream back response                   |
| `add_operator(op)`      | Register an operator (tool provider) with the client         |
| `close()`               | Tear down session and clean up resources                     |
| Operator declaration     | Language-idiomatic way to define a group of tools            |
| Tool declaration         | Language-idiomatic way to mark a method/function as a tool   |
| Tool schema generation   | Auto-generate OpenAI function-call schema from tool signatures |

### Design Principles

1. **Language-idiomatic** — use decorators in Python, attributes in C++, decorators/types in TS. Don't force one language's patterns onto another.
2. **Minimal surface** — expose only what the user needs. Internal transport, serialization, and routing stay private.
3. **Schema from code** — tool parameter schemas must be derived from type annotations/hints, not hand-written JSON.
4. **Streaming-first** — all response handling is streaming by default via callbacks or async iterators.
5. **No cross-import** — the SDK package must NEVER import from `dynamic_agent_service`. It is a standalone dependency.

### Operator & Tool Convention

- An Operator groups related tools under a namespace
- Each Operator has a description (what it can do) and optionally a flow (step-by-step instructions)
- Each Tool has: name, description, parameters (with types + descriptions), and a handler
- Parameter descriptions come from docstrings / JSDoc / comments — not from a separate schema file

---

## Part 2: RAG System Development

### Architecture Overview

The RAG system is a **dynamic, LLM-driven knowledge base** with:
- **Buckets** — isolated namespaces for knowledge (multi-tenant)
- **Blueprints** — LLM-generated schemas for entity types (e.g., "Person", "Product")
- **Instances** — filled blueprint entities stored with embeddings
- **Hybrid retrieval** — combines dense embeddings + BM25 sparse vectors

### Storage

- **PostgreSQL** — stores buckets, blueprints, blueprint attributes, and instance metadata
- **Milvus** — stores attribute values as vectors (dense + sparse) for hybrid search

### Key Workflows

#### Inbound Pipeline (Knowledge Ingestion)

Located in `workflow/inbound/`:

1. **InboundTaskWorkflow** — identifies entity types and creates tasks for each entity instance
2. **BlueprintMatchingWorkflow** — finds existing blueprint or triggers generation
3. **BlueprintGenerationWorkflow** — LLM generates blueprint schema with validation
4. **BlueprintFillingWorkflow** — extracts content from text into structured attributes (accepts `enriched_query` for guidance)
5. **PersistInstanceWorkflow** — handles collision detection, merging, and persistence

**Entry point:** `KnowledgeInterface.inbound(query, text, bucket_name)`

#### Retrieval Pipeline

Located in `workflow/retrieve/`:

1. **KnowledgeRetrieveWorkflow** — decides similarity focus (embedding vs BM25), performs hybrid search, reconstructs instances

**Entry point:** `KnowledgeInterface.retrieve(query, bucket_name, top_k, score_threshold)`

### Design Principles

1. **LLM-driven schema** — blueprints are generated/matched by LLM, not hardcoded
2. **Collision detection** — LLM compares identifiers to detect duplicate entities
3. **Hybrid retrieval** — adaptive weighting between semantic and keyword search
4. **Workflow composition** — all workflows extend `WorkflowBase`, share engines and logs via `execute_subflow()`
5. **Parallel processing** — use `asyncio.gather` for multi-entity tasks
6. **Human-readable names** — blueprint names use proper capitalization (e.g., "Person", "Product")
7. **Markdown chunking** — attributes stored as formatted markdown for readability

### Bucket Management

- **Create:** `KnowledgeAccessor.create_bucket(bucket)`
- **Delete:** `KnowledgeAccessor.delete_bucket(bucket_name)` — ACID transaction (PostgreSQL first, then Milvus)
- **List:** `KnowledgeAccessor.get_bucket_list()`

### Testing Pattern

For RAG tests, use the **one-time-use bucket** pattern:
1. Create bucket
2. Run inbound workflow
3. Dump knowledge to cache
4. Delete bucket

See `tests/test_one_time_inbound.py` for reference.

---

## General Rules

1. **Service and client must be separate** — NEVER import from each other
2. **Simplify implementation** — avoid unnecessary abstractions
3. **No error catch unless told** — let errors propagate for debugging
4. **Use English for communication** — code, docs, and prompts in English
5. **Minimal code** — write only what's needed to solve the problem
6. **Filter non-string values** — before embedding, ensure all values are strings (not bool, None, etc.)
7. **Warm up embedding engine** — call `KnowledgeEngine.get_embeddings(["init"])` before creating Milvus collections

---

## File Structure

```
dynamic_agent_service/
├── agent/                    # LLM engine, agent interface
├── knowledge/                # RAG accessors and interfaces
│   ├── knowledge_interface.py
│   ├── knowledge_accessor.py
│   ├── blueprint_accessor.py
│   └── knowledge_node_accessor.py
├── external_service/         # PG, Milvus, embedding engine
└── operator/                 # Tool execution

workflow/
├── inbound/                  # Knowledge ingestion workflows
│   ├── inbound_task_workflow.py
│   ├── blueprint_generation_workflow.py
│   ├── blueprint_filling_workflow.py
│   └── persist_instance_workflow.py
├── retrieve/                 # Knowledge retrieval workflows
│   └── knowledge_retrieve_workflow.py
└── workflow_base.py          # Base class for all workflows

packages/
└── dynamic_agent_client/     # Python SDK (standalone package)

tests/
├── test_one_time_inbound.py  # RAG inbound test
└── dump_knowledge.py         # Dump utility
```

---

## When Working On...

### SDK Development
- Reference `packages/dynamic_agent_client/` as the canonical Python implementation
- Ensure no imports from `dynamic_agent_service/`
- Auto-generate tool schemas from type annotations
- Use language-idiomatic patterns

### RAG Development
- All workflows extend `WorkflowBase`
- Use `execute_subflow()` for composition
- Blueprint names are human-readable (e.g., "Person", not "person")
- Filter values before embedding (strings only)
- Use `asyncio.gather` for parallel processing
- Test with one-time-use buckets

### Service Development
- Keep service and client separate
- Use PostgreSQL transactions for ACID guarantees
- Initialize embedding engine before Milvus collection creation
- Follow the workflow composition pattern