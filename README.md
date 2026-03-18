uv run -m dynamic_agent_service

# Operator
How to use the operator:
1. Define a class inheriting from `AgentOperator`.
2. Use `@agent_tool` to define methods that can be called by the agent.
3. (Optional) Use `@description` and `@flow` to provide high-level context and guidance to the agent about how to use the operator.
4. Register the operator instance using `await client.add_operator(operator_instance)`.

```python
from dynamic_agent_client import AgentOperator, agent_tool, description, flow

class MyOperator(AgentOperator):
    @description
    def get_description(self):
        return "Description for the agent"

    @flow
    def get_flow(self):
        return "1. step one\n2. step two"

    @agent_tool(description="Do something")
    def my_tool(self, arg1: str) -> str:
        return f"Done with {arg1}"
```

# Session Logic

## Start Up
```mermaid
sequenceDiagram
    participant C as Client
    participant S as Service
    participant LLM as LLM Engine

    C->>S: Create Session (HTTP POST)
    S->>S: Create RealtimeSession
    S->>S: Initialize AGI (AgentGeneralInterface)
    S-->>C: Return session_id & WebSocket URL
    C->>S: Connect WebSocket
    C->>S: Register Operator (HTTP POST)
    S->>S: Store ServiceOperator & Update AGI Menu
```

## Trigger (includes operator usage)
```mermaid
sequenceDiagram
    participant C as Client
    participant S as Service
    participant LLM as LLM Engine

    C->>S: Trigger (HTTP POST with text)
    S->>S: Forge Message List (System + History + User)
    loop until no more tool calls
        S->>LLM: Invoke (Messages + Tools)
        LLM-->>S: Return Text and/or Tool Calls
        S->>C: Stream Text (WebSocket)
        alt Tool Calls present
            S->>C: Execute Tool Call (HTTP POST to Client Webhook)
            C->>C: Execute Operator Tool
            C-->>S: Return Tool Result
            S->>S: Append Tool Result to Messages
        end
    end
    S->>C: Final Chunk (finished=True)
```

# Logging
Rules for logging (implemented in `SessionLogger`):
- All logs are stored in the directory defined by `CACHE_DIR` environment variable.
- Logs are organized by session: `CACHE_DIR/session_log/{session_id}/`.
- Logs are stored in JSONL format with a `timestamp` field.
- **`setting.jsonl`**: Stores session configuration and initial settings.
- **`trigger_{n}.jsonl`**: Created for each trigger event, logging tools available, initial messages, LLM responses, tool calls, results, and compaction events.
- Writes are performed asynchronously using a background worker queue to avoid blocking main execution.
