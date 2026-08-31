# DynamicAgent Python Client

The Python client connects to the DynamicAgent service over HTTP and WebSocket,
registers local operators, triggers agent runs, and exposes typed streaming and
lifecycle subscriptions.

## Install the Client from the Service

The service distributes the exact client wheel bundled with the running service.
Discover the immutable wheel URL through:

```text
GET /sdk/manifest.json
```

Example response:

```json
{
  "service_version": "0.1.0",
  "protocol_version": "1",
  "python_sdk": {
    "package": "dynamic-agent-client",
    "version": "0.3.0",
    "requires_python": ">=3.11",
    "filename": "dynamic_agent_client-0.3.0-py3-none-any.whl",
    "url": "/sdk/python/dynamic_agent_client-0.3.0-py3-none-any.whl",
    "sha256": "<artifact-sha256>"
  }
}
```

PowerShell installation with `uv`:

```powershell
$serviceUrl = [Uri]"http://localhost:7777"
$manifest = Invoke-RestMethod -Uri "$serviceUrl/sdk/manifest.json"
$wheelUrl = [Uri]::new($serviceUrl, $manifest.python_sdk.url).AbsoluteUri
uv add $wheelUrl
```

PowerShell installation with `pip`:

```powershell
$serviceUrl = [Uri]"http://localhost:7777"
$manifest = Invoke-RestMethod -Uri "$serviceUrl/sdk/manifest.json"
$wheelUrl = [Uri]::new($serviceUrl, $manifest.python_sdk.url).AbsoluteUri
pip install $wheelUrl
```

The wheel itself is served from:

```text
GET /sdk/python/<wheel-filename>
```

`GET /sdk/python` redirects to the wheel bundled with the service. Reproducible
projects should store the immutable filename URL and SHA-256 returned by the
manifest instead of persisting the redirect URL.

When running the service directly from a source checkout, build the artifact
before starting the service:

```powershell
uv build --package dynamic-agent-client --out-dir sdk_dist
```

The Docker image performs this build automatically. Set
`DYNAMIC_AGENT_SDK_DIST_DIR` only when the service should read wheels from a
different directory.

## Connect and Create a Session

```python
from dynamic_agent_client import DynamicAgentClient


await DynamicAgentClient.connect("http://localhost:7777")

client = await DynamicAgentClient.create(
    setting="You are a concise research assistant.",
    persist=False,
)
```

`connect()` configures the shared service address. `create()` creates the agent
session and opens its WebSocket connection.

## Subscribe to Chunks and Events

The client exposes two subscription levels:

- `on_chunk` receives every low-level `AgentResponseChunk` from main runners and
  subagents.
- `on_event` receives high-level `AgentInvocationEvent` and
  `ToolExecutionEvent` objects.

There is no subagent visibility flag. Consumers decide what to retain by reading
`runner_id`, `parent_runner_id`, and `parent_tool_call_id`.

```python
from dynamic_agent_client import (
    AgentEvent,
    AgentInvocationEvent,
    AgentResponseChunk,
    ToolExecutionEvent,
)


def on_chunk(chunk: AgentResponseChunk) -> None:
    # Display only main-runner streamed text.
    if chunk.parent_runner_id is None and chunk.text and not chunk.finished:
        print(chunk.text, end="", flush=True)


def on_event(event: AgentEvent) -> None:
    if isinstance(event, AgentInvocationEvent):
        print(
            "invocation",
            event.invocation_id,
            event.runner_id,
            event.total_tokens,
            event.finished,
        )
        return

    if event.status == "started":
        print("tool started", event.tool_call_id, event.name, event.arguments)
    elif event.status == "succeeded":
        print("tool succeeded", event.tool_call_id, event.name, event.result)
    elif event.status == "failed":
        print("tool failed", event.tool_call_id, event.name, event.error)


answer = await client.trigger(
    "Research the requested market and summarize the evidence.",
    on_chunk=on_chunk,
    on_event=on_event,
)
```

Callbacks are synchronous and should remain lightweight. Schedule long-running
or blocking persistence work outside the callback.

## Agent Invocation Events

One `AgentInvocationEvent` is emitted for every provider-model invocation. It
contains:

- `session_id` and client-generated `invocation_id`
- `runner_id` and optional `runner_name`
- `parent_runner_id` and `parent_tool_call_id`
- text accumulated during that invocation
- prompt, completion, and total token usage when reported
- `finished`

`finished=True` means this invocation completed its runner. `finished=False`
means the invocation produced tool calls and the runner can invoke the model
again after their results arrive.

## Tool Execution Events

Each local tool execution emits two `ToolExecutionEvent` objects with the same
`tool_call_id`.

Successful lifecycle:

```text
started -> succeeded
```

Failed lifecycle:

```text
started -> failed
```

The started event contains the normalized arguments. A succeeded event contains
the result. A failed event contains a concise error and does not expose a result
as though execution succeeded.

## Filter Main Runners and Subagents

Main-runner chunk or event:

```python
is_main = item.parent_runner_id is None
```

Subagent chunk or event:

```python
is_subagent = item.parent_runner_id is not None
```

Correlate a subagent with the tool call that launched it using
`parent_tool_call_id`. Tool events use `tool_call_id`, allowing a consumer to
reconstruct the runner and tool execution tree.

## Define and Register an Operator

```python
from dynamic_agent_client import AgentOperator, agent_tool, description


class SearchOperator(AgentOperator):
    @description
    def describe(self) -> str:
        return "Searches the configured market-data source."

    @agent_tool(description="Search for market records")
    async def search(self, query: str) -> list[dict]:
        """:param query: Search text"""
        return [{"query": query, "result": "example"}]


await client.add_operator(SearchOperator())
```

Tool schemas are derived from method signatures and docstrings.

## Close the Client

```python
await client.close()
```

An async context manager can guarantee cleanup:

```python
client = await DynamicAgentClient.create(
    setting="You are a concise assistant.",
)

async with client:
    answer = await client.trigger("Summarize the current findings.")
```
