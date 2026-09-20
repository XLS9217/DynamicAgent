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

Sessions write conversation messages to PostgreSQL and cache them in Redis.
Closing a client disconnects it; expiration removes its runtime state and Redis
cache while retaining database history and invocation logs.

```python
client = await DynamicAgentClient.create("You are a concise assistant.")
```

Save the generated session ID and pass it to `create` later to load its
conversation history. Runtime tasks and registered operators are not restored:

```python
await DynamicAgentClient.connect("http://localhost:7777")

client = await DynamicAgentClient.create(
    "You are a concise assistant.",
)
session_id = client.session_id
await client.close()

client = await DynamicAgentClient.create(
    "You are a concise assistant.",
    session_id=session_id,
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

## Subscribing to agent output

The client provides two levels of agent subscription. `on_chunk` receives every
typed chunk from main runners and subagents. Consumers can distinguish them with
`parent_runner_id`; the client does not filter subagent chunks.

`on_event` receives high-level typed events independently of `on_chunk`. An
`AgentInvocationEvent` is emitted after each provider-model invocation and includes
accumulated text, token usage, runner relationships, and `finished`. A value of
`finished=True` means that invocation completed its runner; `False` means it
produced tool calls and the runner will invoke the model again after receiving
their results. A `ToolExecutionEvent` is emitted when a tool starts and when it
succeeds or fails.

```python
from dynamic_agent_client import (
    AgentEvent,
    AgentInvocationEvent,
    AgentResponseChunk,
    ToolExecutionEvent,
)


def handle_chunk(chunk: AgentResponseChunk) -> None:
    if chunk.text and chunk.parent_runner_id is None:
        print(chunk.text, end="", flush=True)


def handle_event(event: AgentEvent) -> None:
    if isinstance(event, AgentInvocationEvent):
        print(event.runner_id, event.total_tokens, event.finished)
    elif isinstance(event, ToolExecutionEvent):
        print(event.name, event.status)


answer = await client.trigger(
    "What is the weather in Shanghai?",
    on_chunk=handle_chunk,
    on_event=handle_event,
)
```

`@agent_tool` requires an `async def` method and builds the function schema from its signature and docstring. Use nonblocking I/O so streaming and cancellation remain responsive.
Use `count_limit=N` to limit a tool to `N` executions per trigger. When the limit
is exceeded, the tool returns a clear limit-reached message and the underlying
method is not called. Counters reset at the start of the next `client.trigger(...)`.

Tool execution is observed through `on_event` using the same subscription as
model invocations.

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
