# dynamic-agent-client

WebSocket + HTTP client library for consuming the dynamic agent service.

## Installing the client (in another project)

The client is published as its own git repo:
`https://github.com/XLS9217/DynamicAgentClient.git`

The package name is `dynamic-agent-client`; import it as `dynamic_agent_client`.

pip:

```bash
pip install "git+https://github.com/XLS9217/DynamicAgentClient.git"
```

uv:

```bash
uv add "git+https://github.com/XLS9217/DynamicAgentClient.git"
```

Pin to a tag/branch/commit for reproducibility:

```bash
uv add "git+https://github.com/XLS9217/DynamicAgentClient.git@v0.1.2"
```

Then:

```python
from dynamic_agent_client import ...
```

## Sessions

Sessions keep conversation messages in Redis by default. This supports reconnects
and shared access from service instances without writing chat history to
PostgreSQL. After the disconnected session's reconnect window, session cleanup
removes both the in-process session and its Redis history, so smoke tests require
no manual deletion.

```python
client = await DynamicAgentClient.create("You are a concise assistant.")
```

For durable history, set `persist=True`. Save the generated session ID and pass
it to `create` later with the same option to resume the conversation:

```python
await DynamicAgentClient.connect("http://localhost:7777")

client = await DynamicAgentClient.create(
    "You are a concise assistant.",
    persist=True,
)
session_id = client.session_id
await client.close()

client = await DynamicAgentClient.create(
    "You are a concise assistant.",
    session_id=session_id,
    persist=True,
)
```

## Using operators

Operators expose client-side Python functions as tools the agent can call during
`client.trigger(...)`.

```python
from dynamic_agent_client import DynamicAgentClient, AgentOperator, agent_tool, description, flow


class WeatherOperator(AgentOperator):
    @description
    def describe(self) -> str:
        return "Provides weather reports for known cities."

    @flow
    def workflow(self) -> str:
        return "Use get_weather when the user asks for a city weather report."

    @agent_tool(description="Get the weather for a city", count_limit=2)
    async def get_weather(self, city: str) -> str:
        """
        :param city: City name to look up.
        """
        return f"{city}: sunny"


await DynamicAgentClient.connect("http://localhost:7777")
client = await DynamicAgentClient.create("You are a concise assistant.")
await client.add_operator(WeatherOperator())

answer = await client.trigger("What is the weather in Shanghai?")
```

`@agent_tool` builds the function schema from the method signature and docstring.
Use `count_limit=N` to limit a tool to `N` executions per trigger. When the limit
is exceeded, the tool returns a clear limit-reached message and the underlying
method is not called. Counters reset at the start of the next `client.trigger(...)`.

You can observe tool execution with client hooks:

```python
client.on_tool_call(lambda tool_name, arguments: print(tool_name, arguments))
client.on_tool_result(lambda tool_name, arguments, result: print(tool_name, result))
```

### RAG operator

RAG is also an operator now. Register it on the client when a session should use a
knowledge bucket:

```python
from dynamic_agent_client import RagOperator

await client.add_operator(RagOperator(bucket_name="my_bucket"))
answer = await client.trigger("Answer using the knowledge bucket.")
```

`RagOperator.retrieve` has a per-trigger `count_limit` of 2. The agent must call
the RAG tool itself; passing `bucket_name=` to `client.trigger(...)` no longer
injects retrieved knowledge into the agent message list.

To customize RAG results, subclass `RagOperator`. If you override a tool method,
decorate the override with `@agent_tool`; an undecorated override replaces the
parent method and will not be registered as a tool.

```python
from dynamic_agent_client import RagOperator, agent_tool


class CustomRagOperator(RagOperator):
    @agent_tool(
        description="Retrieve relevant knowledge for the user's query from the configured bucket.",
        count_limit=2,
    )
    async def retrieve(self, query: str):
        result = await super().retrieve(query)
        return {
            "client_note": "Prefer directly relevant records.",
            "results": result,
        }
```

## Pushing changes to the client repo

The client is developed here in the monorepo under `dynamic_agent_client/`, but
the standalone repo (`client_origin`) has those folder contents at its **root**.
The two are kept in sync with `git subtree` using the prefix `dynamic_agent_client`.

After committing your changes in the monorepo, push the subtree:

```bash
git subtree push --prefix=dynamic_agent_client client_origin main
```

`client_origin` is already configured as a remote:
`https://github.com/XLS9217/DynamicAgentClient.git`

If the remote is missing on a fresh clone, add it first:

```bash
git remote add client_origin https://github.com/XLS9217/DynamicAgentClient.git
```

Remember to bump `version` in `pyproject.toml` when publishing changes that
consumers should pick up, and tag the release if you pin by tag.
