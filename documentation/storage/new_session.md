# New Session Message Storage

Session history uses PostgreSQL for message metadata, Redis for a rebuildable
cache, and `MEDIA_DIR` for image bytes. PostgreSQL and Redis store image
references only. Base64 image data is created only while building a model
request.

## Configuration

```env
MEDIA_DIR=E:/DynamicAgentData/media
```

`MEDIA_DIR` is required when a request contains an image. The service resolves
it to an absolute path during startup and creates it if necessary. Client paths
and filenames are never joined directly to this directory.

## PostgreSQL Schema

The requested message fields are `message_id`, `session_id`, and JSONB
`content`. `create_at` remains a separate storage field because session history
needs deterministic ordering.

```sql
CREATE TABLE session_message (
    message_id UUID PRIMARY KEY,
    session_id TEXT NOT NULL,
    create_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    content    JSONB NOT NULL,

    CONSTRAINT session_message_content_is_object
        CHECK (jsonb_typeof(content) = 'object')
);

CREATE INDEX idx_session_message_history
    ON session_message (session_id, create_at, message_id);
```

The role moves into the JSONB document. The top-level `version` allows the
format to evolve without guessing which shape an older row uses.

### Text message

```json
{
  "version": 1,
  "role": "user",
  "parts": [
    {
      "type": "text",
      "text": "Hello"
    }
  ]
}
```

### Text and image message

```json
{
  "version": 1,
  "role": "user",
  "parts": [
    {
      "type": "text",
      "text": "What is happening in this image?"
    },
    {
      "type": "image",
      "media_id": "5ccf3e2c-c53c-43cd-969f-1a89ee10f77c",
      "relative_path": "5c/5ccf3e2c-c53c-43cd-969f-1a89ee10f77c.png",
      "mime_type": "image/png",
      "byte_size": 184231,
      "sha256": "7a8c...",
      "detail": "auto"
    }
  ]
}
```

Assistant messages use the same document with `role: "assistant"` and normally
contain one text part. Tool messages may use a later part type; they do not need
a separate table shape.

## Application Models

```python
class TextPart(BaseModel):
    """Store one text segment in its original position."""

    type: Literal["text"] = "text"
    text: str


class StoredImagePart(BaseModel):
    """Reference one validated image below MEDIA_DIR."""

    type: Literal["image"] = "image"
    media_id: UUID
    relative_path: str
    mime_type: Literal["image/png", "image/jpeg", "image/webp", "image/gif"]
    byte_size: int
    sha256: str
    detail: Literal["auto", "low", "high"] = "auto"


MessagePart = Annotated[TextPart | StoredImagePart, Field(discriminator="type")]


class MessageContent(BaseModel):
    """Persist one ordered conversation message."""

    version: Literal[1] = 1
    role: Literal["system", "user", "assistant", "tool"]
    parts: list[MessagePart] = Field(min_length=1)
```

The database boundary validates JSONB through `MessageContent`. Other service
code receives typed content rather than unstructured dictionaries.

## Filesystem Layout

```text
MEDIA_DIR/
  .staging/
    {media_id}.upload
  5c/
    5ccf3e2c-c53c-43cd-969f-1a89ee10f77c.png
  a1/
    a14d....jpg
```

The first two characters of `media_id` form a shard directory. The service
chooses the extension from the detected MIME type. Original filenames are not
used as paths.

Every resolved media path must remain below the resolved `MEDIA_DIR`. The
service rejects absolute paths, `..` components, symbolic-link escapes,
unsupported image formats, excessive file counts, and images over the
configured size limit.

## Write Flow

The filesystem and PostgreSQL cannot share one transaction. The write order
therefore prefers harmless orphan files over committed messages with missing
images.

1. Receive the trigger as `multipart/form-data`: JSON request metadata plus raw
   image parts.
2. Validate the declared MIME type, inspect the actual image format, enforce
   count and size limits, and calculate SHA-256.
3. Generate `message_id` and one `media_id` per image. Build the final JSONB
   document with relative paths.
4. Write every image to `MEDIA_DIR/.staging`, flush it, then atomically rename it
   to its final path under `MEDIA_DIR`.
5. Insert the complete `session_message` row in a PostgreSQL transaction.
6. If the database transaction fails, remove the files finalized for that
   message. A periodic orphan cleanup handles process crashes between steps 4
   and 5.
7. Append the same message document to
   `session:{session_id}:messages` in Redis. If this cache write fails, delete
   the Redis key so the next read rebuilds it from PostgreSQL.

The service does not publish a message or start the model call until all files
and the PostgreSQL row are durable.

## Read and Model Request Flow

1. Load message documents from Redis. On a cache miss, load ordered JSONB rows
   from PostgreSQL, validate them, and repopulate Redis.
2. Keep stored image blocks as references while the history is in memory.
3. Immediately before a model invocation, resolve and read each referenced
   file, verify its size and optional hash, and create the provider content
   block:

```json
{
  "type": "image_url",
  "image_url": {
    "url": "data:image/png;base64,...",
    "detail": "auto"
  }
}
```

The temporary base64 value is sent to the active OpenAI-compatible endpoint and
is not written to PostgreSQL, Redis, or invocation logs. Text-only messages are
converted to the same provider format or may remain plain strings when the
adapter supports both forms.

## Delete and Cleanup Flow

Session deletion first reads all image paths referenced by that session, then
deletes its PostgreSQL messages in one transaction and clears the Redis key.
After the database commit, it removes the referenced files. A failed file
deletion leaves an orphan but cannot leave a surviving message with a broken
reference.

A maintenance job scans `MEDIA_DIR` and removes:

- stale files under `.staging`;
- final files not referenced by any `session_message.content` image block; and
- empty shard directories.

Normal session expiration continues to remove only in-memory state and the
Redis cache. It retains PostgreSQL history and media files. Explicit session
deletion removes both history and media.

## Migration

Existing rows contain separate `role` and text `content` columns. Migration
wraps each text value in the versioned message document before removing the old
role column:

```sql
ALTER TABLE session_message ADD COLUMN content_v2 JSONB;

UPDATE session_message
SET content_v2 = jsonb_build_object(
    'version', 1,
    'role', role,
    'parts', jsonb_build_array(
        jsonb_build_object('type', 'text', 'text', content)
    )
);

ALTER TABLE session_message ALTER COLUMN content_v2 SET NOT NULL;
ALTER TABLE session_message DROP COLUMN content;
ALTER TABLE session_message DROP COLUMN role;
ALTER TABLE session_message RENAME COLUMN content_v2 TO content;
```

The migration must run in a transaction after a database backup. Application
deployment must not mix old writers with the new schema.

The repository provides the same guarded migration as an explicit command:

```powershell
python -m dynamic_agent_service.migrate_session_messages
```

Stop old service processes before running it, then start only the new version.
