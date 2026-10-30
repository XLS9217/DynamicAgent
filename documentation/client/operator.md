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

Tools must use `async def` and nonblocking I/O; synchronous tools are rejected by `@agent_tool`. If your operator defines `__init__`, call `super().__init__()` to collect its decorated methods. Register operators again when recreating a client session. See [Quick Start](quick-start.md) for installation.

`client.stop()` cancels tool tasks. Use awaitable operations so cancellation can interrupt waits. Tool cancellation does not roll back external actions.

## Argument Schemas

The decorator uses Pydantic to generate argument schemas from annotations and defaults. It supports integers, numbers, objects, nested lists and dictionaries, unions, nullable types, `Literal` enums, and Pydantic models with field constraints. Parameters without defaults are required; a nullable annotation alone does not make a parameter optional.

Docstring `:param` descriptions are preserved. Nested model definitions remain in the schema's `$defs`. This generates ordinary function-tool schemas; it does not enable strict tool calling or perform runtime argument validation. Incoming objects remain dictionaries; call `YourModel.model_validate(value)` inside the tool if you need a model instance.

## Dynamic Parameter Limits

Use `operator.inject_param_limit(...)` to constrain a tool parameter using values known only when the operator instance is created. The SDK generates the base JSON Schema from the decorated method, then applies these instance-specific limits before serializing the operator for registration. You do not need to override `get_serialized_operator()`.

```python
def inject_param_limit(
    self,
    tool_name: str,
    param_name: str,
    limits: dict,
) -> None:
    ...
```

- `tool_name` is the Python method name, such as `submit_labels`, without the operator prefix.
- `param_name` is an existing top-level argument of that method.
- `limits` contains JSON Schema constraints for that parameter. Use `enum` for a scalar choice and `items: {"enum": ...}` for choices inside a list.

Call it after `super().__init__()` and before `await client.add_operator(operator)`. Limits belong to that instance; they do not modify the decorator, another instance, or a caller-owned dictionary.

### Dynamic Choices and Selection Limits

```python
class LabelOperator(AgentOperator):
    """Submit labels selected from the current task's allowed names."""

    def __init__(self, label_names: list[str], max_labels: int):
        """Configure the choices for this operator instance."""
        self.allowed_labels = tuple(dict.fromkeys(label_names))
        self.max_labels = max_labels
        super().__init__()

        self.inject_param_limit(
            "submit_labels",
            "labels",
            {
                "items": {"enum": list(self.allowed_labels)},
                "minItems": 1,
                "maxItems": self.max_labels,
                "uniqueItems": True,
            },
        )

    @agent_tool(description="Submit the selected label names")
    async def submit_labels(self, labels: list[str]) -> str:
        """Accept the selected labels.

        :param labels: Names chosen from the current task's label list.
        """
        # Validate before accepting a model's submission.
        if not 1 <= len(labels) <= self.max_labels:
            return "Invalid selection count; submit the complete selection again."
        if len(labels) != len(set(labels)) or any(
            label not in self.allowed_labels for label in labels
        ):
            return "Unknown or duplicate label; submit the complete selection again."
        return ", ".join(labels)


operator = LabelOperator(["Marketing", "Sales", "Support"], max_labels=2)
await client.add_operator(operator)
```

The serialized tool is named `LabelOperator_submit_labels`. Its parameter schema contains:

```json
{
  "type": "object",
  "properties": {
    "labels": {
      "type": "array",
      "items": {
        "type": "string",
        "enum": ["Marketing", "Sales", "Support"]
      },
      "minItems": 1,
      "maxItems": 2,
      "uniqueItems": true
    }
  },
  "required": ["labels"]
}
```

The example omits generated titles and descriptions. Those remain present in the actual schema.

### Other Constraints and Nested Parameters

The same function accepts scalar enums, numeric bounds, string constraints, and nested constraints:

```python
self.inject_param_limit("submit_selection", "status", {
    "enum": ["related", "unrelated", "deferred"],
})
self.inject_param_limit("search", "limit", {"minimum": 1, "maximum": 20})
self.inject_param_limit("submit_selection", "results", {
    "minItems": len(target_ids),
    "maxItems": len(target_ids),
    "items": {
        "properties": {
            "target_id": {"enum": target_ids},
            "selection": {
                "items": {"enum": branch_names},
                "maxItems": max_labels,
            },
        },
    },
})
```

For nested constraints, the corresponding fields must already be defined by annotations or a Pydantic model. For example, annotate `results` as a list of a model defining `target_id` and `selection`; `list[dict]` alone does not declare those fields. Injection constrains the existing structure rather than introducing a new argument shape.

### Schema and Lifecycle Rules

- Constraint dictionaries merge recursively into the selected parameter schema. Lists and scalar values replace the previous value at the same key. For example, injecting `items.enum` preserves the generated `items.type`.
- Repeated calls accumulate constraints; the latest value for the same constraint wins. Replacing an `enum` replaces the whole choice list. Each registration uses the resulting schema at that time.
- The SDK works on deep copies of generated schemas and supplied limits. Constraints on a referenced Pydantic model are applied to a private copy of the referenced schema, so other parameters using that model retain their original constraints.
- Unknown tool or parameter names, unsupported constraint keywords, incompatible constraint types, empty enums, and inconsistent bounds raise `ValueError` during injection. Constraint keywords include `enum`, `const`, numeric bounds, string length/pattern constraints, array length/uniqueness constraints, nested `items`/`properties`, and constraint alternatives/combinations through `anyOf`/`allOf`. Each alternative narrows the existing typed schema. Structural changes such as replacing `type`, `$ref`, `$defs`, or `required` are rejected. Enum values must satisfy the declared parameter type and existing static constraints; injected limits cannot weaken static constraints.
- Referenced models must use nonrecursive local references for the constrained parameter. Injection rejects recursive or external references with `ValueError`.
- Injection preserves the method signature, argument defaults, required fields, tool name, and description. It does not enable strict tool calling or add Python arguments.
- Registration sends a schema snapshot to the service. Changing local limits does not update a registered tool automatically. For a new task context, create a new operator with its limits and register it in the intended session. Do not change limits while a turn is running.

These limits describe the arguments the model should produce. Provider support for individual JSON Schema keywords varies, and `inject_param_limit` does not perform runtime argument validation. Continue validating incoming arguments and business rules in the tool before accepting a result or performing an action. For labeling, that includes complete target/category coverage, duplicate detection, category-to-label membership, and resolving names to the task's frozen IDs.

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
