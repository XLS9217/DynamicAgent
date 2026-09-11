# Session Log Storage

Conversation messages and model invocation logs are stored separately and linked through the user message ID.

| Content | Location | Description |
| --- | --- | --- |
| Persisted messages | PostgreSQL `session_message` | Message ID, session ID, creation time, role, and content |
| Live message cache | Redis `session:{session_id}:messages` | Ordered JSON messages, each containing `role` and `content` |
| Model invocation logs | `{CACHE_DIR}/trigger_log/{trigger_id}.jsonl` | One JSON line per completed model call; `CACHE_DIR` defaults to `.cache` |

## Writes and Associations

1. When the user triggers a turn, the user message is written to PostgreSQL and Redis.
2. Its `message_id` becomes the turn's `trigger_id` and determines the log filename. Multiple model calls in the same turn append to the same file.
3. Each invocation record contains invocation and trigger IDs, runner and parent-runner IDs, response text, tool calls and results, model resource ID, token usage, and error information.
4. The final assistant message is written to PostgreSQL and Redis.

Association: `session_id -> session_message.message_id -> trigger_log/{message_id}.jsonl`. Without a trigger context, the filename uses the current `invoke_id` instead.

The invocation record itself contains no `session_id`, timestamp, or complete input conversation. Query the PostgreSQL message record to identify the session and trigger time.

## Trigger Log Structure

A **trigger** is one user-triggered turn. An **invoke** is one model service call. A trigger can contain multiple invokes from the main runner and subagents, all appended to one file.

```text
trigger_log/
  {user_message_id}.jsonl
    Line 1: Model call A returns a tool-call request
    Line 2: Model call B reads the tool result and returns an answer
```

The format is JSONL: **one complete JSON object per line, with no enclosing array**. A record is written when a call succeeds or ends with an exception, not for each streamed text chunk. Concurrent calls appear in append order; line numbers do not establish call start order.

### Invocation Record

| Field | Type | Description |
| --- | --- | --- |
| `invoke_id` | `str` | UUID generated independently for each invocation record |
| `trigger_id` | `str / null` | User message ID for this turn; normally also the log filename |
| `runner_id` | `str` | Runner that initiated the call |
| `parent_runner_id` | `str / null` | Parent runner ID; normally `null` for the main runner |
| `text` | `str / null` | Complete text returned by this model call; not necessarily the final answer for the turn |
| `tool_id` | `str / null` | Tool-call ID when the response contains exactly one tool call; `null` for zero or multiple calls |
| `tool_use` | `dict / null` | Tool calls requested by this response, shaped as `{"items": [...]}` |
| `tool_result` | `dict / null` | All `role=tool` messages in this call's input, shaped as `{"items": [...]}`; may include results already logged earlier |
| `resource_id` | `str` | Associated model resource ID, corresponding to `openai_resource.resource_id`; not an API key |
| `prompt_tokens` | `int / null` | Input token count |
| `completion_tokens` | `int / null` | Output token count |
| `usage_detail` | `dict / null` | Input, output, and total token counts for successful calls; the current handler may leave counts at 0 when the provider supplies no usage |
| `error` | `dict / null` | `{"type": "ExceptionClass", "message": "error description"}` on failure; `null` on success |

Each entry in `tool_use.items` contains `id`, `name`, `arguments`, `session_id`, and `runner_id`. `arguments` is a JSON string; the last two fields may be `null`. `tool_result.items` contains input tool messages, usually with `role`, `tool_call_id`, and `content`. `tool_call_id` links each result to an earlier tool request.

Tool execution does not generate a separate invocation record. Typically, call A records the request in `tool_use`, and call B records the result passed back to the model in `tool_result`.

### Two-Call Example

These two lines belong to the same `trigger-1.jsonl` file. IDs are shortened for readability; actual `invoke_id` values and normal `trigger_id` values are UUIDs.

```jsonl
{"invoke_id":"invoke-a","trigger_id":"trigger-1","runner_id":"main-1","parent_runner_id":null,"text":null,"tool_id":"call-1","tool_use":{"items":[{"id":"call-1","name":"get_weather","arguments":"{\"city\":\"Shanghai\"}","session_id":null,"runner_id":null}]},"tool_result":null,"resource_id":"resource-1","prompt_tokens":100,"completion_tokens":20,"usage_detail":{"prompt_tokens":100,"completion_tokens":20,"total_tokens":120},"error":null}
{"invoke_id":"invoke-b","trigger_id":"trigger-1","runner_id":"main-1","parent_runner_id":null,"text":"It is sunny in Shanghai today.","tool_id":null,"tool_use":null,"tool_result":{"items":[{"role":"tool","tool_call_id":"call-1","content":"Sunny"}]},"resource_id":"resource-1","prompt_tokens":130,"completion_tokens":10,"usage_detail":{"prompt_tokens":130,"completion_tokens":10,"total_tokens":140},"error":null}
```

## Reading and Cleanup

- Read messages from Redis first. On a cache miss, load PostgreSQL history ordered by `create_at` and repopulate the cache.
- Read JSONL logs directly from the filesystem. The former monitoring endpoints and log-browsing/clearing helpers have been removed; log writing remains.
- Session expiration deletes the Redis message cache but retains PostgreSQL messages and log files.
- Explicit session deletion removes PostgreSQL and Redis messages but leaves JSONL files. Deleting those message records also removes the database link between the logs and their session.
