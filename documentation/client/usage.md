# Client Usage

The client supports two basic cases: chat and chat with tools. Start the service with an enabled model resource configured, then connect to its URL. Each example below is a complete script.

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

## Session Lifetime

- `await client.close()` closes the client connection. `reconnect_keep` defaults to 30 seconds; expired session objects and Redis caches are removed by periodic cleanup.
- User and final assistant messages are always stored in PostgreSQL and cached in Redis. Closing a connection does not delete history or invocation logs.
- Save `client.session_id` and later pass it to `create(setting=..., session_id=...)` to load message history. Register tools again; previous runtime tasks are not restored.
- To delete messages, save the session ID, close the client, then call `await DynamicAgentClient.delete_session(session_id)` before stopping the shared HTTP client. JSONL logs remain.
- Call `ServiceHandler.stop()` only when all sessions using the shared HTTP client have finished.
