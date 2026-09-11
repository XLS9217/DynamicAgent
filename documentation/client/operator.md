# Operators

An `AgentOperator` groups Python methods that the model can call as tools. Register an instance with `await client.add_operator(...)`. The service sends tool requests to the SDK, which runs the methods in your client process and returns their results automatically.

## Define and Use an Operator

- `@agent_tool` exposes a method. Type annotations and `:param` docstrings describe its arguments to the model.
- `@description` supplies the operator's purpose.
- Optional `@flow` methods supply instructions for using its tools.
- Optional `count_limit` limits tool executions per trigger; counters reset on the next trigger.

```python
import asyncio

from dynamic_agent_client import AgentOperator, DynamicAgentClient, agent_tool, description
from dynamic_agent_client.service_handler import ServiceHandler


class Calculator(AgentOperator):
    """Provide an addition tool."""

    @description
    def describe(self) -> str:
        """Describe the operator to the model."""
        return "Adds two numbers."

    @agent_tool(description="Add two numbers", count_limit=2)
    async def add(self, a: float, b: float) -> float:
        """Return the sum.

        :param a: First number.
        :param b: Second number.
        """
        return a + b


async def main():
    """Register the calculator and trigger a task."""
    await DynamicAgentClient.connect("http://localhost:7777")
    client = await DynamicAgentClient.create(setting="Use the calculator for arithmetic.")
    await client.add_operator(Calculator())
    answer = await client.trigger("Add 23 and 19 using the calculator.")
    print(answer)
    await client.close()
    await ServiceHandler.stop()


asyncio.run(main())
```

Tools may be synchronous or asynchronous. If your operator defines `__init__`, call `super().__init__()` to collect its decorated methods. Register operators again when recreating a client session. See [Quick Start](quick-start.md) for installation.

## Official Operator: `SubagentOperator`

`SubagentOperator` is the SDK's current built-in operator. It lets the model create subagents and delegate tasks within the same session. You provide candidate operator instances; the model chooses which ones each subagent receives.

Using the `Calculator` above, replace `main()` with:

```python
from dynamic_agent_client import SubagentOperator


async def main():
    """Delegate arithmetic to a subagent."""
    await DynamicAgentClient.connect("http://localhost:7777")
    client = await DynamicAgentClient.create(
        setting="Delegate arithmetic to a subagent with the Calculator operator.",
    )
    await client.add_operator(SubagentOperator(candidate_operators=[Calculator()]))
    answer = await client.trigger("Ask a calculator subagent to add 23 and 19.")
    print(answer)
    await client.close()
    await ServiceHandler.stop()
```

The model uses two tools:

| Tool | Purpose |
| --- | --- |
| `init_subagent(name, setting, operator_list)` | Create a reusable subagent and return its `runner_id`. Operator names are candidate class names, such as `Calculator`. |
| `trigger_subagent(runner_id, task)` | Dispatch a self-contained task. The completed subagent response returns to the parent as a tool result. |

At least one candidate operator is required to initialize a subagent, and candidate class names must be unique. Candidates are available to subagents; register them separately with `client.add_operator()` if the main agent also needs direct access. The SDK supplies execution context automatically, so let the model call these tools through `client.trigger()`.
