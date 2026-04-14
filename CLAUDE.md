
We always use English as our communication language.

# What this repo is
A monorepo for the generic agentic runtime
Two packages live here:
- `dynamic_agent_service/` — the runnable FastAPI service (LLM loop, memory, tool execution, session management)
- `packages/dynamic_agent_client/` — pip-installable SDK that other services install to communicate with the service

rule:
1. do not do error catch unless I told you to
2. simplify implementation
3. service and client should separate, NEVER import from each other