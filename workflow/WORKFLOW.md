# Workflow Guide

This folder uses a small async workflow framework based on `WorkflowBase`.

## Core Design

Each workflow:
- Inherits from `WorkflowBase`
- Implements `async def execute(self)`
- Uses `self._append_log("...")` for structured logs

`WorkflowBase` provides:
- `execute_subflow(...)`: create + wire + execute child workflow
- `get_log()`: return current workflow logs
- `save_jsonl(path)`: save current workflow logs as JSONL

## WorkflowBase API

Location: `workflow/workflow_base.py`

### `_append_log(message: str)`
Adds a record:
- `workflow`: class name
- `function_name`: function that called `_append_log`
- `time`: ISO timestamp
- `message`: your message

If this workflow is a subflow, logs are also forwarded to caller workflow automatically.

### `execute_subflow(workflow_cls, *args, **kwargs)`
Use this inside a parent workflow when calling a child workflow.

It handles:
1. Child workflow creation
2. Log forwarding setup (`child -> parent`)
3. Child `execute()` call

### `save_jsonl(file_path)`
Writes one log record per line (JSONL).

## How To Create a New Workflow

```python
from workflow.workflow_base import WorkflowBase

class MyWorkflow(WorkflowBase):
    def __init__(self, arg1: str):
        super().__init__()
        self.arg1 = arg1

    async def execute(self):
        self._append_log("start")
        # do work
        self._append_log("done")
        return {"ok": True}
```

## How To Call a Subworkflow

Inside parent workflow:

```python
result = await self.execute_subflow(ChildWorkflow, child_arg1, child_arg2)
```

Do not manually set caller logger and do not add caller logger into child `__init__`.

## Existing Examples

- `BlueprintGenerationWorkflow` uses `execute_subflow(JsonFixWorkflow, ...)` when LLM JSON is malformed.
- `BlueprintFillingWorkflow` uses the same pattern for JSON repair fallback.

## Log Persistence Pattern

For one workflow = one file:

```python
workflow.save_jsonl("cache/my_workflow.jsonl")
```

For multiple workflows:

```python
wf1.save_jsonl("cache/wf1.jsonl")
wf2.save_jsonl("cache/wf2.jsonl")
```

## Recommended Conventions

- Keep one workflow instance for one run.
- Keep `execute()` as orchestration; move details to private methods (`_step_xxx`).
- Log important boundaries:
  - input received
  - external call start/end
  - parse/fallback branch
  - final output size/count
- Use `execute_subflow` whenever nesting workflows so log propagation stays consistent.
