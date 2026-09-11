# Session Design

The server represents a live session with `RealtimeSession`. It owns the connection, message-storage entry points, and task scheduling. Its `AgentGeneralInterface` and `AgentRunner` objects manage model calls and tool execution state. A Session is an in-memory object, not a database row.

## Object Relationships

```
RealtimeSessionManager
+-- _sessions[session_id] -> RealtimeSession
    +-- Configuration: session_id / setting / reconnect_keep
    +-- Connection: client (WebSocket) / disconnect_time
    +-- Tasks: active_trigger_task / subagent_tasks
    +-- agi: AgentGeneralInterface
        +-- openai_adapter: selected model service connection
        +-- _operator_list: main runner's tool definitions
        +-- _runner: main AgentRunner
        +-- _runner_by_id: index of main and subagent runners
        +-- _subagent_config_by_runner_id: subagent configuration

Shared services, associated by session_id
+-- SessionAccessor -> Redis message cache / PostgreSQL message history
+-- LogInterface -> current resource and trigger context -> JSONL invocation logs
```

## RealtimeSession Fields

| Field                   | Type                               | Initial value                        | Description                                                                                                                       |
| ----------------------- | ---------------------------------- | ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------- |
| `session_id`          | `str`                            | Caller-provided or generated UUID v4 | Session identifier and manager lookup key                                                                                         |
| `setting`             | `str`                            | Required at creation                 | Session instructions used to construct the system prompt                                                                          |
| `reconnect_keep`      | `int`                            | `30`                               | Retention window after disconnect, in seconds                                                                                     |
| `disconnect_time`     | `float / None`                   | `None`                             | Unix timestamp of disconnect; cleared on reconnect                                                                                |
| `client`              | `WebSocket / None`               | `None`                             | Current client connection; a new connection replaces and closes the old one                                                       |
| `agi`                 | `AgentGeneralInterface / None`   | `None`                             | Created by`agent_setup()`; manages the main runner and subagents                                                                |
| `active_trigger_task` | `asyncio.Task / None`            | `None`                             | Main trigger task created by the HTTP endpoint; not the sole indicator of the full tool-interaction lifecycle                     |
| `subagent_tasks`      | `set[asyncio.Task]`              | Empty set                            | Subagent trigger tasks, automatically removed from the set when they finish                                                       |
| `state`               | `AgentState`, read-only property | Initially`IDLE`                    | Usually the main runner's state; returns`RUNNING` when the main trigger task is still active but the runner is temporarily idle |

`resource_id` and `trigger_id` are stored in `LogInterface._contexts[session_id]`, not directly on the Session. The Session also does not directly maintain a complete message-history list.

## Runner Structure and State

Each `AgentRunner` owns a `runner_id`, name, parent-runner reference, current input messages (`_running_message_list`), tool definitions (`_tools`), pending tool calls (`pending_tool_calls`), received tool results (`pending_tool_results`), and accumulated response text. A subagent also uses `parent_tool_call_id` to link to the tool call initiated by its parent.

| State         | Enum value                | Meaning                                          |
| ------------- | ------------------------- | ------------------------------------------------ |
| `IDLE`      | `idle`                  | Ready for a new trigger                          |
| `RUNNING`   | `running`               | Calling the model or processing the current turn |
| `GATHERING` | `gathering_tool_result` | Waiting for tool results from the client         |

The typical flow is `IDLE -> RUNNING -> GATHERING -> RUNNING -> IDLE`. Without tool calls, the runner moves directly from `RUNNING` to `IDLE`. Session `state` primarily reflects the main runner, not an aggregate of all subagent states. Connection status is tracked separately through `disconnect_time`.

## Session Lifecycle

1. **Create:** `POST /create_session` accepts `setting`, `reconnect_keep`, and `session_id`. The manager registers the in-memory object. Setup selects the highest-priority enabled, non-deleted model resource, creates the AGI, and configures the logging resource context. The response includes the session ID, main runner ID, WebSocket URL, and available message history.
2. **Connect:** `/agent_session?session_id=...` attaches the WebSocket, registers the streaming callback, and resends outstanding tool calls. Tool definitions are registered through `POST /agent_operator`.
3. **Trigger:** `POST /trigger` accepts a request only while the session is idle. It loads prior history, then writes the current user message. That message's ID becomes `trigger_id`. AGI builds model input from the system prompt, history, and current user input.
4. **Tools and subagents:** Tool requests travel to the client over WebSocket. The client returns results through `POST /tool_result`, and `runner_id` routes them to the correct runner. `/init_subagent` and `/trigger_subagent` manage subagents, which share their Session's communication and logging association.
5. **Complete:** When the main runner finishes, its accumulated assistant text is saved and the current trigger logging context is cleared. Individual model invocation records have already been appended to the turn's JSONL file.
6. **Disconnect and expire:** Disconnect records a timestamp. The session becomes eligible for expiration after `reconnect_keep` seconds. Every 10 seconds, the manager removes expired in-memory objects, deletes Redis message caches, and releases logging contexts. Persisted messages and log files remain.

## Storage and Recovery Boundaries

| Data                                                                    | Location                                       | Recovery behavior                                        |
| ----------------------------------------------------------------------- | ---------------------------------------------- | -------------------------------------------------------- |
| Session objects, connections, tasks, registered tools, and runner state | Current server process memory                  | Not automatically restored after a service restart       |
| Message cache                                                           | Redis`session:{session_id}:messages`         | Restores message content, not full runtime state         |
| Persisted messages                                                      | PostgreSQL`session_message`                  | Loaded and copied into Redis on a cache miss             |
| Invocation logs                                                         | `{CACHE_DIR}/trigger_log/{trigger_id}.jsonl` | Used for tracing calls, not as execution-state snapshots |

- User messages and final assistant messages both go to PostgreSQL and Redis. There is no separate ephemeral session mode.
- Reconnecting a WebSocket uses the object still held by the manager. Calling the creation endpoint with the same `session_id` creates and replaces the in-memory object; it does not restore the previous runner. Loading history does not restore pending tool state.
- `SessionMeta` defines a metadata model, but there is currently no implementation writing `session:{session_id}:meta`, and no PostgreSQL session master table.
- Explicit session deletion closes the current connection, removes the in-memory entry, and deletes PostgreSQL/Redis messages. It does not delete JSONL files. Neither deletion nor expiration currently explicitly cancels all running tasks.

Sources: [session_management.py](../../dynamic_agent_service/service/session_management.py), [service_router.py](../../dynamic_agent_service/service/service_router.py), [agent_general_interface.py](../../dynamic_agent_service/agent/agent_general_interface.py), and [agent_runner.py](../../dynamic_agent_service/agent/agent_runner.py). For log structure, see [session_log.md](../storage/session_log.md).
