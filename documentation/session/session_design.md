# Session Design

The server creates a `ChatAgentSession` or `TaskAgentSession`. Their abstract base, `AgentSessionBase`, owns the connection, message-storage entry points, and task scheduling. Its `AgentGeneralInterface` and `AgentRunner` objects manage model calls and tool execution state. A Session is an in-memory object, not a database row.

Every session has a `session_type` storage policy:

- `chat` stores messages in PostgreSQL and Redis.
- `task` keeps messages in process memory and image bytes in a short-lived Redis cache, removes its history and media when the session expires, and is the default.

Chat sessions also configure the memory and context-compaction hooks on the main runner.

## Object Relationships

```
SessionManager
+-- _sessions[session_id] -> ChatAgentSession | TaskAgentSession
    +-- Configuration: session_id / session_type / setting / reconnect_keep
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

## Shared Session Fields

| Field                   | Type                               | Initial value                        | Description                                                                                                                       |
| ----------------------- | ---------------------------------- | ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------- |
| `session_id`          | `str`                            | Caller-provided or generated UUID v4 | Session identifier and manager lookup key                                                                                         |
| `session_type`        | `Literal["chat", "task"]`      | `"task"`                             | Storage policy fixed when the session is created                                                                                  |
| `setting`             | `str`                            | Required at creation                 | Session instructions used to construct the system prompt                                                                          |
| `reconnect_keep`      | `int`                            | `30`                               | Retention window after disconnect, in seconds                                                                                     |
| `disconnect_time`     | `float / None`                   | `None`                             | Unix timestamp of disconnect; cleared on reconnect                                                                                |
| `client`              | `WebSocket / None`               | `None`                             | Current client connection; a new connection replaces and closes the old one                                                       |
| `agi`                 | `AgentGeneralInterface / None`   | `None`                             | Created by`agent_setup()`; manages the main runner and subagents                                                                |
| `active_trigger_task` | `asyncio.Task / None`            | `None`                             | Main trigger task created by the HTTP endpoint; not the sole indicator of the full tool-interaction lifecycle                     |
| `subagent_tasks`      | `set[asyncio.Task]`              | Empty set                            | Subagent trigger tasks, automatically removed from the set when they finish                                                       |
| `state`               | `AgentState`, read-only property | Initially`IDLE`                    | Usually the main runner's state; returns`RUNNING` when the main trigger task is still active but the runner is temporarily idle |

The Session stores the current execution `trigger_id`. `LogInterface._contexts[session_id]` also stores it alongside `resource_id` and the separate persisted user `message_id`. The Session also does not directly maintain a complete message-history list.

## Runner Structure and State

Each `AgentRunner` owns a `runner_id`, name, parent-runner reference, current input messages (`_running_message_list`), tool definitions (`_tools`), pending tool calls (`pending_tool_calls`), received tool results (`pending_tool_results`), and accumulated response text. A subagent also uses `parent_tool_call_id` to link to the tool call initiated by its parent.

| State         | Enum value                | Meaning                                          |
| ------------- | ------------------------- | ------------------------------------------------ |
| `IDLE`      | `idle`                  | Ready for a new trigger                          |
| `RUNNING`   | `running`               | Calling the model or processing the current turn |
| `GATHERING` | `gathering_tool_result` | Waiting for tool results from the client         |

The typical flow is `IDLE -> RUNNING -> GATHERING -> RUNNING -> IDLE`. Without tool calls, the runner moves directly from `RUNNING` to `IDLE`. Session `state` primarily reflects the main runner, not an aggregate of all subagent states. Connection status is tracked separately through `disconnect_time`.

## Session Lifecycle

1. **Create:** `POST /create_session` accepts `setting`, `reconnect_keep`, `session_id`, and `session_type`. The type defaults to `task` and cannot change for the lifetime of that session ID. Callers that require durable history must explicitly request `chat`. The manager registers the in-memory object and writes Redis metadata for chats. Setup selects the highest-priority enabled, non-deleted model resource, creates the AGI, and configures the logging resource context. The response includes the session ID, session type, main runner ID, WebSocket URL, and available message history.
2. **Connect:** `/agent_session?session_id=...` attaches the WebSocket, registers the streaming callback, and resends outstanding tool calls. Tool definitions are registered through `POST /agent_operator`.
3. **Trigger:** `POST /trigger` accepts a request only while the session is idle. It reserves the SDK-provided `trigger_id` (or generates one), loads prior history, then writes the current user message. Chat messages are written to PostgreSQL before Redis; task messages stay in the session object. All execution messages and logs share `trigger_id`. AGI builds model input from the system prompt, history, and current user input.
4. **Tools and subagents:** Tool requests travel to the client over WebSocket. The client returns results through `POST /tool_result`, and `runner_id` routes them to the correct runner. `/init_subagent` and `/trigger_subagent` manage subagents, which share their Session's communication and logging association.
5. **Complete:** When the main runner finishes, its accumulated assistant text is saved and the current trigger logging context is cleared. Individual model invocation records have already been appended to the turn's JSONL file.
6. **Disconnect and expire:** Disconnect records a timestamp. The session becomes eligible for expiration after `reconnect_keep` seconds. Every 10 seconds, the manager removes expired in-memory objects and releases logging contexts. Chat expiration clears cached messages and retains session metadata for resumption. Task expiration releases the session and its in-memory messages and Redis image cache. PostgreSQL chat messages and JSONL invocation logs remain.

## Storage Policies

| Behavior | `chat` | `task` |
| --- | --- | --- |
| Live session object | Process memory | Process memory |
| Message history | PostgreSQL and Redis | Process memory |
| Redis cache miss | Restore from PostgreSQL | Return empty history |
| History after expiration | Retained in PostgreSQL | Deleted |
| Referenced media after expiration | Retained | Deleted |
| Explicit deletion | PostgreSQL, Redis, and media | Release session memory |
| Invocation JSONL logs | Retained | Retained |

Chat sessions delegate durable storage to SessionAccessor. Task sessions keep their own ordered message list.

## Redis Keys

Chat storage and temporary image cache use separate key prefixes:

```text
chat:{session_id}:meta
chat:{session_id}:messages
task:{session_id}:image:{media_id}
```

The metadata document contains at least:

```json
{
  "session_id": "example-id",
  "session_type": "chat",
  "setting": "Complete one background task.",
  "reconnect_keep": 30,
  "created_at": 1730000000.0,
  "disconnect_time": null
}
```

The server must reject attempts to recreate a live session ID with a different type. Clients that omit `session_type` create task sessions and do not write messages to PostgreSQL.

## Media Lifecycle

Chat images live under `MEDIA_DIR`. Short-lived sessions keep the full Redis key in each message image part and raw bytes at that key. Live sessions renew the expiry. Session cleanup deletes the image keys.

## Recovery Boundaries

| Data | Location | Recovery behavior |
| --- | --- | --- |
| Connections, running tasks, registered tools, and runner state | Current server process | Not restored after restart |
| Chat messages | PostgreSQL and Redis | Restored from PostgreSQL after a Redis miss |
| Task messages and image references | Process memory | Available during the reconnect window on the same process |
| Chat session metadata | Redis | Restores type and configuration, not active execution state |
| Invocation logs | `{CACHE_DIR}/trigger_log/{trigger_id}.jsonl` | Used for tracing, not execution recovery |

- Reconnecting a WebSocket uses the object still held by the manager. Recreating a chat session restores messages but does not restore a previous runner, pending tools, or active subagents.
- Explicit deletion closes the connection and removes the in-memory entry. It does not delete JSONL files.
- Expiration and deletion must cancel active tasks before removing storage or media.
- Existing Redis chat keys may be invalidated during rollout; PostgreSQL remains the source of truth and repopulates the new chat namespace.
- Changing the default from durable chat to ephemeral task is intentional. Existing callers that depend on persisted history must add `session_type="chat"` when creating a session.

Sources: [session management](../../dynamic_agent_service/service/session_management), [service_router.py](../../dynamic_agent_service/service/service_router.py), [agent_general_interface.py](../../dynamic_agent_service/agent/agent_general_interface.py), and [agent_runner.py](../../dynamic_agent_service/agent/agent_runner.py). For log structure, see [session_log.md](session_log.md).
