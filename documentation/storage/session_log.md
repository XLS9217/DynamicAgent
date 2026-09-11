# 会话日志存储

会话消息与模型调用日志分别存储，通过用户消息 ID 关联。

| 内容         | 存储位置                                       | 说明                                                             |
| ------------ | ---------------------------------------------- | ---------------------------------------------------------------- |
| 持久化消息   | PostgreSQL`session_message`                  | 保存消息 ID、会话 ID、创建时间、角色和正文                       |
| 实时消息缓存 | Redis`session:{session_id}:messages`         | 按顺序保存消息 JSON，每项包含`role` 和 `content`             |
| 模型调用日志 | `{CACHE_DIR}/trigger_log/{trigger_id}.jsonl` | 每次完成的模型调用追加一行 JSON；`CACHE_DIR` 默认是 `.cache` |

## 写入与关联

1. 用户触发一次对话时，用户消息始终写入 PostgreSQL 和 Redis，即使会话设置为 `persist=false`。
2. 该用户消息的 `message_id` 作为本轮 `trigger_id`，用于命名日志文件。同一轮中的多次模型调用追加到同一个文件。
3. 每条调用日志记录调用 ID、触发 ID、执行器及父执行器 ID、响应文本、工具调用与结果、模型资源 ID、Token 用量和错误信息。
4. 最终助手消息写入 Redis；会话设置为 `persist=true` 时，也写入 PostgreSQL。

关联路径：`session_id → session_message.message_id → trigger_log/{message_id}.jsonl`。没有触发上下文时，日志文件以本次 `invoke_id` 命名。

调用日志本身不包含 `session_id`、时间戳或完整输入对话；会话归属和触发时间需通过 PostgreSQL 消息记录查询。

## Trigger 日志结构

一个 **trigger** 对应一次用户触发；一个 **invoke** 对应一次模型服务调用。一次 trigger 可以包含主执行器、子执行器的多次 invoke，统一追加到同一个文件中。

```text
trigger_log/
  {用户消息 ID}.jsonl
    第 1 行：模型调用 A，返回工具调用请求
    第 2 行：模型调用 B，读取工具结果并返回回答
```

文件采用 JSONL 格式：**每行一个完整 JSON 对象，没有外层数组**。调用成功或异常结束时写入一条记录，不逐条记录流式文本片段。并发调用按实际写入顺序排列，不能将行号理解为调用开始顺序。

### 单条调用记录

| 字段                  | 类型            | 说明                                                                                          |
| --------------------- | --------------- | --------------------------------------------------------------------------------------------- |
| `invoke_id`         | `str`         | 本次模型调用日志的 UUID，每条记录独立生成                                                     |
| `trigger_id`        | `str / null`  | 本轮用户消息 ID，也是正常情况下的日志文件名                                                   |
| `runner_id`         | `str`         | 发起调用的执行器 ID                                                                           |
| `parent_runner_id`  | `str / null`  | 父执行器 ID；主执行器通常为`null`                                                           |
| `text`              | `str / null`  | 本次模型返回的完整文本，不一定是本轮最终回答                                                  |
| `tool_id`           | `str / null`  | 本次响应恰好包含一个工具调用时，保存该调用的 ID；零个或多个时为`null`                       |
| `tool_use`          | `dict / null` | 本次模型响应提出的工具调用，结构为`{"items": [...]}`                                        |
| `tool_result`       | `dict / null` | 本次模型输入中所有`role=tool` 的消息，结构为 `{"items": [...]}`；可能包含之前已记录的结果 |
| `resource_id`       | `str`         | 本次日志关联的模型资源 ID，对应`openai_resource.resource_id`；不是 API 密钥                 |
| `prompt_tokens`     | `int / null`  | 输入 Token 数                                                                                 |
| `completion_tokens` | `int / null`  | 输出 Token 数                                                                                 |
| `usage_detail`      | `dict / null` | 当前成功调用写入输入、输出和总 Token 数；未收到供应商用量时，当前处理器可能保留为 0           |
| `error`             | `dict / null` | 调用异常时为`{"type": "异常类名", "message": "异常说明"}`，成功时为 `null`                |

`tool_use.items` 中每项包含 `id`、`name`、`arguments`、`session_id`、`runner_id`；其中 `arguments` 是 JSON 字符串，后两个字段可以为 `null`。`tool_result.items` 保存输入中的工具消息，通常包含 `role`、`tool_call_id` 和 `content`，通过 `tool_call_id` 与先前的工具请求关联。

工具执行本身不会单独生成一条 invoke 日志。通常先在调用 A 的 `tool_use` 中看到工具请求，随后在调用 B 的 `tool_result` 中看到传回模型的工具结果。

### 两次调用示例

以下用简化 ID 展示同一个 `trigger-1.jsonl` 的两行内容；实际 `invoke_id` 和正常的 `trigger_id` 为 UUID。

```jsonl
{"invoke_id":"invoke-a","trigger_id":"trigger-1","runner_id":"main-1","parent_runner_id":null,"text":null,"tool_id":"call-1","tool_use":{"items":[{"id":"call-1","name":"get_weather","arguments":"{\"city\":\"Shanghai\"}","session_id":null,"runner_id":null}]},"tool_result":null,"resource_id":"resource-1","prompt_tokens":100,"completion_tokens":20,"usage_detail":{"prompt_tokens":100,"completion_tokens":20,"total_tokens":120},"error":null}
{"invoke_id":"invoke-b","trigger_id":"trigger-1","runner_id":"main-1","parent_runner_id":null,"text":"上海今天晴。","tool_id":null,"tool_use":null,"tool_result":{"items":[{"role":"tool","tool_call_id":"call-1","content":"晴"}]},"resource_id":"resource-1","prompt_tokens":130,"completion_tokens":10,"usage_detail":{"prompt_tokens":130,"completion_tokens":10,"total_tokens":140},"error":null}
```

## 读取与清理

- 消息优先从 Redis 读取；缓存为空且启用持久化时，从 PostgreSQL 按 `create_at` 加载并回填缓存。
- 当前直接从文件系统读取 JSONL 日志；原监控接口及日志浏览、清空功能已移除，日志写入仍保留。
- 会话过期时删除 Redis 消息缓存，保留 PostgreSQL 消息和日志文件。
- 显式删除会话时删除 PostgreSQL 和 Redis 消息，但不会删除 JSONL 文件；此后日志与会话之间的数据库关联也随消息记录消失。
