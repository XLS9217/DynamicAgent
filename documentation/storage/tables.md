# 数据表设计总览

依据当前仓库的建表脚本和数据读写代码整理。PostgreSQL 共 2 张表；Milvus 集合和 Redis 缓存结构单独分组。`PK` 表示主键，隐含非空约束和唯一索引。未标注 DEFAULT 的字段未声明数据库默认值。

## 会话消息（PostgreSQL）

### `session_message`

每条持久化会话消息一行，保存会话标识、角色、正文和创建时间，作为 Redis 缓存未命中时的历史数据来源。

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `message_id` | `UUID` | PK | 持久化写入时由应用生成 UUID v4 |
| `create_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `NOW()` | 消息创建时间；实际字段名为 create_at |
| `session_id` | `TEXT` | NOT NULL | 会话标识，无会话主表外键 |
| `role` | `TEXT` | NOT NULL | 消息角色，模型注释列举 system、user、assistant |
| `content` | `TEXT` | NOT NULL | 消息正文 |

约束和索引：

- `INDEX idx_session_message_session_id (session_id, create_at)`，用于按会话读取并按时间排序。
- `session_id` 无外键；当前没有会话主表。`role` 无数据库枚举检查。
- `durable = true` 时先写 PostgreSQL 再写 Redis，否则只写 Redis；会话创建参数 `persist` 默认是 `false`，访问器的 `durable` 参数默认是 `true`。
- 缓存为空且启用持久化时，按 `create_at` 加载历史并回填 Redis；相同时间戳未指定额外排序字段。
- 会话过期仅清理消息缓存，保留持久化历史；`delete_session()` 删除该会话的 PostgreSQL 消息和 Redis 消息列表。

## 模型服务资源（PostgreSQL）

### `openai_resource`

每个 OpenAI 兼容模型服务配置一行，保存连接参数、启用状态、选用优先级和软删除时间。

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `resource_id` | `TEXT` | PK | 创建方法生成的 UUID v4 字符串 |
| `model` | `TEXT` | NOT NULL | 模型名称 |
| `api_key` | `TEXT` | NOT NULL | API 密钥；当前访问器直接存取文本 |
| `base_url` | `TEXT` | NOT NULL | OpenAI 兼容服务地址 |
| `deleted_at` | `TIMESTAMPTZ` | NULL | 软删除时间；未删除时为 NULL |
| `enabled` | `BOOLEAN` | NOT NULL, DEFAULT `TRUE` | 是否参与资源选用 |
| `priority` | `INTEGER` | NOT NULL, DEFAULT `0` | 数值越大，选用优先级越高 |

约束和索引：

- `CHECK (deleted_at IS NULL OR enabled = FALSE)`，约束名为 `openai_resource_deleted_disabled`，保证软删除资源不能启用。
- `INDEX idx_openai_resource_enabled (enabled, priority DESC)`。
- 模型名称和服务地址未设置唯一约束；`priority` 无非负约束。
- 选用条件为 `enabled = TRUE AND deleted_at IS NULL`，按 `priority DESC, resource_id` 排序并取第一条。
- 软删除设置 `deleted_at = COALESCE(deleted_at, NOW())` 和 `enabled = FALSE`，保留记录及首次删除时间。

## 向量存储（Milvus）

### `{collection_name}`

调用方通过 `MilvusInstance.create_hybrid_collection(collection_name, dimension)` 创建独立集合，每条记录保存文本及其向量，不依赖 PostgreSQL 业务表。集合名由调用方提供。

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `kn_id` | `VARCHAR` | PK, max_length=64 | 调用方提供的记录 ID，保留该字段名以兼容现有向量调用 |
| `value` | `VARCHAR` | max_length=65535, enable_analyzer=True | 文本内容，同时作为 BM25 输入 |
| `sparse_vector` | `SPARSE_FLOAT_VECTOR` | 由 BM25 函数生成 | 文本稀疏向量，无需调用方写入 |
| `embedding` | `FLOAT_VECTOR` | dim=dimension | 稠密向量，维度须与集合创建参数一致 |

约束和索引：

- `auto_id=False`、`enable_dynamic_field=False`，按 `kn_id` 执行 upsert 和删除。
- `embedding`：`AUTOINDEX`，度量为 `COSINE`。
- `sparse_vector`：`SPARSE_INVERTED_INDEX`，度量为 `BM25`；函数 `bm25` 从 `value` 生成稀疏向量。
- 稠密检索使用 `search(..., vector_field="embedding")`；混合检索使用 `hybrid_search()`，通过 WeightedRanker 合并结果。
- 已存在的集合不自动修改，调用方需确保结构兼容。已有的通用 `create_collection()` 快速创建方法仍保留，但不会创建上述混合检索结构。
- KnowledgeEngine 继续提供嵌入服务；Milvus 方法可独立调用，不依赖会话或旧知识模型。

## 会话缓存（Redis）

### `session:{session_id}:messages`

每个会话一个 List，每个列表元素为一条消息的 JSON，保存实时消息或持久化历史的缓存。以下字段类型为应用 JSON 模型类型。

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `role` | `str` | 应用模型必填 | 消息角色 |
| `content` | `str` | 应用模型必填 | 消息正文 |

约束和索引：

- 通过 `RPUSH` 追加，`LRANGE 0 -1` 读取；无关系数据库主键、外键或二级索引。
- 列表元素不保存 PostgreSQL 的 `message_id` 和 `create_at`。
- 写入未设置 TTL；当前会话过期清理会删除此键。

`service_structs.py` 中还声明了 `session:{session_id}:meta` 对应的 `SessionMeta` 模型，但未发现实际读写实现，因此未列为已落地结构。调用日志存储在文件中，客户端也没有独立数据库表。
