# Client Quick Start

The client supports two basic cases: chat and chat with tools. Connect to the backend URL provided by your service administrator. Each example below is a complete script.

## Install

Requires Python 3.11 or newer. Add the client to your project from the backend's package index:

```sh
uv add --index "http://localhost:7777/sdk/simple" dynamic-agent-client
```

Replace `http://localhost:7777` with your backend address. The index offers the client version bundled with that backend. The package name is `dynamic-agent-client`; import it as `dynamic_agent_client`.

Your project's lockfile keeps the installed version fixed. After the backend publishes a newer client, upgrade explicitly:

```sh
uv lock --upgrade-package dynamic-agent-client --refresh-package dynamic-agent-client
uv sync
```

`/sdk/python` is a browser download redirect, not a `uv add` package URL. Use `/sdk/simple` for installation and upgrades.

Use your backend URL in `DynamicAgentClient.connect()` below. Save an example as `chat.py` and run it:

```sh
uv run python chat.py
```

## Chat

Create a session and call `trigger()` for each turn. The session supplies previous messages to the model, so follow-up questions can use earlier context.

```python
import asyncio

from dynamic_agent_client import DynamicAgentClient
from dynamic_agent_client.service_handler import ServiceHandler


async def main():
    """Run two conversational turns in the same session."""
    await DynamicAgentClient.connect("http://localhost:7777")
    client = await DynamicAgentClient.create(
        setting="You are a helpful assistant. Reply concisely in English.",
    )

    answer = await client.trigger("My name is Alex. Say hello.")
    print(answer)

    answer = await client.trigger("What is my name?")
    print(answer)

    await client.close()
    await ServiceHandler.stop()


asyncio.run(main())
```

`trigger()` waits for the turn to finish and returns the response text. Await each turn before starting another on the same session. To receive streaming chunks, pass an `on_chunk` callback to `trigger()`.

## Image Input

Pass local image paths with the optional `images` argument. The SDK uploads raw
file bytes to the service; it does not place base64 data in the trigger JSON.

```python
answer = await client.trigger(
    "What is happening in this image?",
    images=["photo.png"],
)
```

The service validates and stores images below `MEDIA_DIR`. PostgreSQL and Redis
store media references only. Images referenced by the selected session history
are converted to temporary provider content blocks immediately before each
model turn. PNG, JPEG, WebP, and GIF files are supported. The active model must
support vision input.

## Tool

An `AgentOperator` exposes client-side Python methods to the model. Decorate callable methods with `@agent_tool`, describe the operator, and register it before triggering the agent.

```python
import asyncio

from dynamic_agent_client import (
    AgentOperator,
    DynamicAgentClient,
    agent_tool,
    description,
    flow,
)
from dynamic_agent_client.service_handler import ServiceHandler


class Calculator(AgentOperator):
    """Expose a local addition tool to the agent."""

    @description
    def describe(self) -> str:
        """Describe the operator's capability."""
        return "Adds two numbers using a local Python function."

    @flow
    def workflow(self) -> str:
        """Explain when the agent should use this operator."""
        return "Use add for addition requests, then report the result."

    @agent_tool(description="Add two numbers", count_limit=2)
    async def add(self, a: float, b: float) -> float:
        """Return the sum of two numbers.

        :param a: First number.
        :param b: Second number.
        :return: The sum.
        """
        return a + b


async def main():
    """Register a tool and let the agent use it during a turn."""
    await DynamicAgentClient.connect("http://localhost:7777")
    client = await DynamicAgentClient.create(
        setting="Use the registered calculator for arithmetic. Reply concisely.",
    )
    await client.add_operator(Calculator())

    answer = await client.trigger("Use the calculator to add 23 and 19.")
    print(answer)

    await client.close()
    await ServiceHandler.stop()


asyncio.run(main())
```

The model requests the tool, the service sends that request over WebSocket, and the SDK executes `add()` locally and returns its result. The model then continues and produces the answer returned by `trigger()`; you do not manually forward tool results in this flow.

Type annotations and `:param` docstrings build the tool argument schema. `count_limit=2` allows at most two executions of this tool per trigger; counters reset on the next trigger. Use `on_event` to observe model invocation and tool execution events.

## Stop a Turn

`await client.stop()` interrupts the active turn, including its subagents and tool waits, while keeping the session connected. It returns after the backend has saved partial text and released the agent. The HTTP response includes the terminal result, so stop does not depend on receiving a WebSocket completion event. The interrupted `trigger()` returns that partial text, and the next trigger can use it as conversation history. Calling `stop()` while idle does nothing.

Run the trigger as a task so a UI action or another coroutine can stop it:

```python
async def main():
    """Stop shortly after text starts, then ask about the partial response."""
    await DynamicAgentClient.connect("http://localhost:7777")
    client = await DynamicAgentClient.create(setting="Reply in English.")
    text_started = asyncio.Event()

    def on_chunk(chunk):
        """Signal when the first text arrives."""
        if chunk.text and not chunk.finished:
            text_started.set()

    pending = asyncio.create_task(client.trigger("Tell me a long story.", on_chunk=on_chunk))
    await text_started.wait()
    await asyncio.sleep(0.05)
    await client.stop()
    partial = await pending
    print(partial)
    answer = await client.trigger("What did you say before I stopped you?")
    print(answer)
    await client.close()
    await ServiceHandler.stop()
```

Use the imports and `asyncio.run(main())` from the Chat example. A Stop button can call `client.stop()` directly while the trigger task is running. All tools must use `async def` and nonblocking operations; tool tasks receive cancellation. Stop does not undo external actions a tool already performed.

## Session Lifetime

- `await client.close()` closes the client connection. `reconnect_keep` defaults to 30 seconds; expired session objects and Redis caches are removed by periodic cleanup.
- User and final assistant messages are always stored in PostgreSQL and cached in Redis. Closing a connection does not delete history or invocation logs.
- Save `client.session_id` and later pass it to `create(setting=..., session_id=...)` to load message history. Register tools again; previous runtime tasks are not restored.
- To delete messages, save the session ID, close the client, then call `await DynamicAgentClient.delete_session(session_id)` before stopping the shared HTTP client. JSONL logs remain.
- Call `ServiceHandler.stop()` only when all sessions using the shared HTTP client have finished.
