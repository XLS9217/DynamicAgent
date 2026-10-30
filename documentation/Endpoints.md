# Dynamic Agent Service Endpoints

This document describes the HTTP and WebSocket API exposed by the Dynamic Agent
service. Unless stated otherwise, examples assume the service is running at
`http://localhost:7777`.

## Conventions

- HTTP request and response bodies are JSON unless the endpoint says otherwise.
- A successful request returns a 2xx response. Validation errors return `422`.
- Missing sessions return `404`; requests that conflict with the current session
  or turn state return `409`.
- Unexpected server errors return `500` with `{ "detail": "Internal server error" }`.
- `trigger_id` values are optional, but a caller should send one when it needs to
  correlate HTTP requests with streamed WebSocket messages. When omitted, the
  service generates one.

## Service

### `GET /health`

Returns the process health status.

```json
{ "status": "healthy" }
```

### `POST /create_session`

Creates a session, initializes its agent, and returns the WebSocket URL and
current history. Supplying an existing `session_id` resumes that session.

Request:

```json
{
  "setting": "You are a concise assistant.",
  "session_type": "chat",
  "reconnect_keep": 30,
  "session_id": null
}
```

`session_type` is `chat` (durable PostgreSQL history) or `task` (temporary Redis
history) and defaults to `task`. `reconnect_keep` is the disconnect retention
period in seconds and defaults to `30`.

Response:

```json
{
  "session_id": "session-id",
  "session_type": "chat",
  "runner_id": "runner-id",
  "socket_url": "ws://localhost:7777/agent_session?session_id=session-id",
  "messages": []
}
```

### `POST /trigger`

Starts one text-only agent turn. The HTTP response acknowledges acceptance;
assistant output is streamed on the session WebSocket.

```json
{
  "session_id": "session-id",
  "text": "Hello",
  "trigger_id": "turn-001"
}
```

Response:

```json
{ "status": "accepted", "trigger_id": "turn-001" }
```

Only one turn may be active for a session. A second active turn returns `409`.

### `POST /trigger_media`

Starts one multimodal turn using `multipart/form-data`. The fields are:

| Field          | Type           | Required | Description                               |
| -------------- | -------------- | -------- | ----------------------------------------- |
| `session_id` | string         | yes      | Target session.                           |
| `text`       | string         | no       | Text prompt; defaults to an empty string. |
| `trigger_id` | string         | no       | Correlation ID.                           |
| `images`     | file, repeated | yes      | PNG, JPEG, WebP, or GIF uploads.          |

The response has the same shape as `/trigger`. Invalid media returns `422`.

### `POST /stop`

Stops the active turn while keeping the session and WebSocket connected. An
outdated or repeated stop is harmless.

```json
{ "session_id": "session-id", "trigger_id": "turn-001" }
```

Response when a turn was stopped:

```json
{
  "status": "stopped",
  "trigger_id": "turn-001",
  "completion": {
    "type": "agent_chunk",
    "text": "Partial response",
    "finished": true,
    "cancelled": true,
    "trigger_id": "turn-001"
  }
}
```

When idle, the response is `{ "status": "idle", "trigger_id": ..., "completion": null }`.

### `DELETE /session/{session_id}`

Stops and removes the live session, deletes persisted session data, and returns:

```json
{ "status": "ok", "session_id": "session-id" }
```

For a chat session this deletes stored messages. JSONL invocation logs are not
deleted by this endpoint.

### `POST /agent_operator`

Registers a serialized client-side operator for a session. The operator payload
is produced by the Python SDK's `get_serialized_operator()` method.

```json
{
  "session_id": "session-id",
  "operator": {
    "name": "calculator",
    "description": "Adds numbers",
    "tools": []
  }
}
```

The response is `{ "status": "ok", "operator_name": "calculator" }`.

## Tool and subagent coordination

These endpoints are normally called by the SDK while a turn is running.

### `POST /tool_result`

Returns the result of a tool call executed by the client.

```json
{
  "session_id": "session-id",
  "trigger_id": "turn-001",
  "runner_id": "runner-id",
  "tool_call_id": "call-id",
  "ok": true,
  "result": "42"
}
```

Returns `{ "status": "ok" }`. If the turn is no longer active, the result is
ignored and the service returns `{ "status": "ignored" }`.

### `POST /init_subagent`

Creates a subagent runner under a parent runner.

```json
{
  "session_id": "session-id",
  "trigger_id": "turn-001",
  "parent_runner_id": "parent-id",
  "name": "researcher",
  "setting": "Find the relevant facts.",
  "operators": [{ "name": "search", "tools": [] }]
}
```

`operators` must contain at least one serialized operator. The response is:

```json
{ "status": "ok", "runner_id": "subagent-id", "name": "researcher" }
```

### `POST /trigger_subagent`

Starts work on an initialized subagent.

```json
{
  "session_id": "session-id",
  "trigger_id": "turn-001",
  "parent_runner_id": "parent-id",
  "parent_tool_call_id": "call-id",
  "runner_id": "subagent-id",
  "task": "Research this question."
}
```

The normal response is `{ "status": "accepted" }`; stale turns return
`{ "status": "ignored" }`.

## WebSocket

### `WS /agent_session?session_id={session_id}`

Connect after `/create_session`. The service sends JSON messages on this socket;
the client does not send turn prompts through it. A missing session closes the
socket with code `4004`.

#### Agent response chunks

```json
{
  "type": "agent_chunk",
  "text": "Hello",
  "finished": false,
  "cancelled": false,
  "trigger_id": "turn-001",
  "invoked": false,
  "prompt_tokens": 0,
  "completion_tokens": 0,
  "total_tokens": 0,
  "runner_id": "runner-id",
  "runner_name": "main",
  "parent_runner_id": null,
  "parent_tool_call_id": null
}
```

The terminal chunk has `finished: true`. A stopped turn also has
`cancelled: true`; its `text` is the partial response.

#### Client tool calls

```json
{
  "type": "tool_call",
  "session_id": "session-id",
  "runner_id": "runner-id",
  "tool_call_id": "call-id",
  "name": "calculator_add",
  "arguments": { "a": 2, "b": 3 },
  "trigger_id": "turn-001"
}
```

The client executes the registered operator and posts the result to
`/tool_result`.

### `WS /echo`

Development endpoint that accepts text frames and sends the same text back.

## SDK distribution

The service exposes the Python client package under `/sdk`.

| Method and path                           | Purpose                                                                              |
| ----------------------------------------- | ------------------------------------------------------------------------------------ |
| `GET /sdk/manifest.json`                | Service and protocol versions, wheel filename, URL, Python requirement, and SHA-256. |
| `GET /sdk/simple/`                      | PEP 503 package index root.                                                          |
| `GET /sdk/simple/dynamic-agent-client/` | PEP 503 index for `dynamic-agent-client`.                                          |
| `GET /sdk/python`                       | `307` redirect to the current wheel.                                               |
| `GET /sdk/python/{filename}`            | Download the exact bundled wheel.                                                    |

Install the SDK from the package index with:

```sh
uv add --index "http://localhost:7777/sdk/simple" dynamic-agent-client
```
