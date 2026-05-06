
We always use English as our communication language.

# What this repo is
A monorepo for the generic agentic runtime
Two packages live here:
- `dynamic_agent_service/` — the runnable FastAPI service (LLM loop, memory, tool execution, session management)
- `packages/dynamic_agent_client/` — pip-installable SDK that other services install to communicate with the service

rule:
1. do not do error catch unless I told you to
2. simplify implementation
3. service and client should separate, NEVER import from each other, unless I told you to
4. To check the server output, read the log file in the cache folder

# Endpoint placement guideline
- If a feature needs to be accessed by the client, the endpoint goes to `service_router.py`
- If a feature is only for monitoring/admin purposes, the endpoint goes to `monitor_router.py`

To implement a new feature in service
1. implement the feature
2. write simple tests in DynamicAgent\tests, make sure to load .env 
3. run with `uv run -m tests.xxx`
4. check the cache folder, the path can be found in .env
5. if it relates to the change If the client's experience is affected, 
   - please update, create, or request the deletion of scripts within DynamicAgent\examples accordingly. 